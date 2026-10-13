"""Deploy / rollback of the target to a specific commit, via systemd --user.

Prod safety rules:
  - only `git checkout --detach <sha>`; never reset --hard / clean (the checkout holds data/, .env, certs/)
  - refuse if tracked files have local modifications
  - dependencies are reinstalled only when requirements.txt differs between the two SHAs
  - after restart, health must be green for `verify_s` seconds or the deploy is reported failed
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass

from flect.sources.health import http_health


@dataclass
class DeployResult:
    ok: bool
    sha: str
    previous_sha: str | None
    detail: str


class Deployer:
    def __init__(self, repo_dir: str, unit: str, url: str, health_path: str, venv: str | None = None,
                 fetch_url: str | None = None):
        self.repo_dir = repo_dir
        self.fetch_url = fetch_url
        self.unit = unit
        self.url = url
        self.health_path = health_path
        self.venv = venv

    def _git(self, *args: str, check: bool = True) -> str:
        res = subprocess.run(["git", "-C", self.repo_dir, *args], capture_output=True, text=True, timeout=300, check=False)
        if check and res.returncode != 0:
            raise RuntimeError(f"git {' '.join(args[:2])}: {res.stderr.strip()[:300]}")
        return res.stdout.strip()

    def current_sha(self) -> str:
        return self._git("rev-parse", "HEAD")

    def has_commit(self, sha: str) -> bool:
        return subprocess.run(["git", "-C", self.repo_dir, "cat-file", "-e", f"{sha}^{{commit}}"],
                              capture_output=True, timeout=30, check=False).returncode == 0

    def tracked_changes(self) -> list[str]:
        out = self._git("status", "--porcelain", "--untracked-files=no")
        return [line for line in out.splitlines() if line.strip()]

    def _systemctl(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["systemctl", "--user", *args, self.unit], capture_output=True, text=True,
                              timeout=60, check=False)

    def wait_healthy(self, verify_s: float = 60, timeout_s: float = 180, interval: float = 3) -> tuple[bool, str]:
        """Healthy = every probe passes for `verify_s` consecutive seconds, within `timeout_s`."""
        deadline = time.monotonic() + timeout_s
        healthy_since = None
        last = ""
        while time.monotonic() < deadline:
            ok, status, _, err = http_health(self.url, self.health_path)
            last = err or f"status {status}"
            if ok:
                healthy_since = healthy_since or time.monotonic()
                if time.monotonic() - healthy_since >= verify_s:
                    return True, "healthy"
            else:
                healthy_since = None
            time.sleep(interval)
        return False, f"not healthy within {timeout_s}s (last: {last})"

    def deploy(self, sha: str, verify_s: float = 60) -> DeployResult:
        previous = self.current_sha()
        dirty = self.tracked_changes()
        if dirty:
            return DeployResult(False, sha, previous, f"refusing: tracked files modified in {self.repo_dir}: {dirty[:5]}")
        if not self.has_commit(sha):
            if self.fetch_url:
                self._git("fetch", "--quiet", self.fetch_url, sha, check=False)
            if not self.has_commit(sha):
                return DeployResult(False, sha, previous, f"commit {sha[:12]} not available in {self.repo_dir}")
        reqs_changed = bool(self._git("diff", "--name-only", previous, sha, "--", "requirements.txt", check=False))
        co = subprocess.run(["git", "-C", self.repo_dir, "checkout", "--quiet", "--detach", sha],
                            capture_output=True, text=True, timeout=300, check=False)
        if co.returncode != 0:
            return DeployResult(False, sha, previous, f"checkout refused (nothing changed): {co.stderr.strip()[:300]}")
        if reqs_changed and self.venv:
            pip = subprocess.run([f"{self.venv}/bin/pip", "install", "-q", "-r", f"{self.repo_dir}/requirements.txt"],
                                 capture_output=True, text=True, timeout=1800, check=False)
            if pip.returncode != 0:
                self._git("checkout", "--quiet", "--detach", previous)
                return DeployResult(False, sha, previous, f"pip install failed; reverted checkout: {pip.stderr[-300:]}")
        res = self._systemctl("restart")
        if res.returncode != 0:
            return DeployResult(False, sha, previous, f"systemctl restart failed: {res.stderr.strip()[:300]}")
        ok, detail = self.wait_healthy(verify_s)
        return DeployResult(ok, sha, previous, detail)

    def restart(self, verify_s: float = 30) -> DeployResult:
        sha = self.current_sha()
        self._systemctl("restart")
        ok, detail = self.wait_healthy(verify_s)
        return DeployResult(ok, sha, sha, detail)

    def start(self) -> bool:
        return self._systemctl("start").returncode == 0

    def stop(self) -> bool:
        return self._systemctl("stop").returncode == 0
