"""git and gh actuators. Every commit and push is made as soczap, verified before it leaves the box.

Hard rules enforced here (see plan §4):
  - repo-local user.name / user.email are soczap's, set on every clone
  - commits pass -c user.name/-c user.email and --no-gpg-sign
  - no --author is ever used
  - before any push, the tip commit's author/committer must be soczap and the message must carry
    NO AI attribution trailer ("Co-Authored-By", "Generated with", "Claude", etc.)
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

FORBIDDEN_TRAILER = re.compile(
    r"^\s*(?:co-authored-by|signed-off-by)\s*:.*(?:claude|anthropic|gpt|openai|copilot|\bbot\b|noreply@anthropic)"
    r"|generated with \[?claude|🤖|co-authored-by:\s*claude",
    re.IGNORECASE | re.MULTILINE)


class IdentityError(RuntimeError):
    pass


class Git:
    def __init__(self, repo_dir: str, name: str, email: str):
        self.dir = Path(repo_dir)
        self.name = name
        self.email = email

    def _run(self, *args: str, check: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess:
        proc = subprocess.run(["git", "-C", str(self.dir), *args], capture_output=True, text=True,
                              input=input_text, timeout=300, check=False)
        if check and proc.returncode != 0:
            raise RuntimeError(f"git {args[0]} failed: {proc.stderr.strip()[:400]}")
        return proc

    def ensure_identity(self) -> None:
        self._run("config", "user.name", self.name)
        self._run("config", "user.email", self.email)
        self._run("config", "commit.gpgsign", "false")

    def current_sha(self, ref: str = "HEAD") -> str:
        return self._run("rev-parse", ref).stdout.strip()

    def tip_author(self) -> tuple[str, str, str, str, str]:
        out = self._run("log", "-1", "--format=%an%x00%ae%x00%cn%x00%ce%x00%B").stdout
        an, ae, cn, ce, body = out.split("\x00", 4)
        return an, ae, cn, ce, body

    def assert_tip_is_soczap(self) -> None:
        an, ae, cn, ce, body = self.tip_author()
        if ae != self.email or ce != self.email or an != self.name or cn != self.name:
            raise IdentityError(f"tip commit author/committer is not {self.name} <{self.email}>: "
                                f"author={an} <{ae}>, committer={cn} <{ce}>")
        if FORBIDDEN_TRAILER.search(body):
            raise IdentityError("tip commit message carries an AI attribution trailer; refusing to push")

    def commit_all(self, message: str) -> str:
        if FORBIDDEN_TRAILER.search(message):
            raise IdentityError("refusing to create a commit with an AI attribution trailer")
        self.ensure_identity()
        self._run("add", "-A")
        self._run("-c", f"user.name={self.name}", "-c", f"user.email={self.email}",
                  "commit", "--no-gpg-sign", "-m", message)
        return self.current_sha()

    def checkout_detached(self, sha: str) -> None:
        self._run("checkout", "--detach", sha)

    def fetch(self, *refspecs: str, remote: str = "origin") -> None:
        self._run("fetch", "--quiet", remote, *refspecs)

    def push(self, refspec: str, remote: str = "origin", force: bool = False) -> None:
        """Push only after proving the tip is soczap's and carries no AI trailer."""
        self.assert_tip_is_soczap()
        args = ["push", remote, refspec]
        if force:
            args.insert(1, "--force-with-lease")
        self._run(*args)


class GitHub:
    """Thin wrapper over the gh CLI (authenticated as soczap). Returns parsed JSON where relevant."""

    def __init__(self, repo: str):
        self.repo = repo

    def api(self, path: str, method: str = "GET", fields: dict | None = None,
            raw: bool = False, paginate: bool = False) -> subprocess.CompletedProcess:
        args = ["gh", "api"]
        if method != "GET":
            args += ["--method", method]
        if paginate:
            args.append("--paginate")
        for key, value in (fields or {}).items():
            args += ["-f", f"{key}={value}"] if isinstance(value, str) else ["-F", f"{key}={value}"]
        args.append(path if path.startswith("/") else f"/repos/{self.repo}/{path}")
        return subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)

    def set_status(self, sha: str, context: str, state: str, description: str, target_url: str = "") -> bool:
        """state: pending | success | failure | error."""
        res = self.api(f"statuses/{sha}", "POST", {"state": state, "context": context,
                                                   "description": description[:140], "target_url": target_url})
        return res.returncode == 0

    def comment(self, issue_or_pr: int, body: str) -> bool:
        res = self.api(f"issues/{issue_or_pr}/comments", "POST", {"body": body})
        return res.returncode == 0

    def add_labels(self, issue_or_pr: int, labels: list[str]) -> bool:
        args = ["gh", "api", f"/repos/{self.repo}/issues/{issue_or_pr}/labels", "--method", "POST"]
        for label in labels:
            args += ["-f", f"labels[]={label}"]
        return subprocess.run(args, capture_output=True, text=True, timeout=30, check=False).returncode == 0

    def open_issue(self, title: str, body: str, labels: list[str] | None = None) -> int | None:
        args = ["gh", "issue", "create", "--repo", self.repo, "--title", title[:250], "--body", body]
        for label in labels or []:
            args += ["--label", label]
        res = subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)
        if res.returncode != 0 and labels and "label" in (res.stderr or "").lower():
            # A missing label must not lose the incident report: retry without labels.
            res = subprocess.run(args[:9], capture_output=True, text=True, timeout=60, check=False)
        m = re.search(r"/issues/(\d+)", res.stdout)
        return int(m.group(1)) if m else None

    def close_pr(self, number: int, comment: str | None = None) -> bool:
        args = ["gh", "pr", "close", str(number), "--repo", self.repo]
        if comment:
            args += ["--comment", comment]
        return subprocess.run(args, capture_output=True, text=True, timeout=60, check=False).returncode == 0

    def merge_pr(self, number: int, head_sha: str, method: str = "squash") -> tuple[bool, str]:
        """Merge only the exact commit that was vetted (--match-head-commit)."""
        res = subprocess.run(["gh", "pr", "merge", str(number), "--repo", self.repo, f"--{method}",
                              "--match-head-commit", head_sha, "--delete-branch"],
                             capture_output=True, text=True, timeout=120, check=False)
        return res.returncode == 0, (res.stderr or res.stdout).strip()[:400]

    def create_pr(self, base: str, head: str, title: str, body: str) -> int | None:
        res = subprocess.run(["gh", "pr", "create", "--repo", self.repo, "--base", base, "--head", head,
                              "--title", title[:250], "--body", body],
                             capture_output=True, text=True, timeout=120, check=False)
        m = re.search(r"/pull/(\d+)", res.stdout)
        return int(m.group(1)) if m else None
