"""Run untrusted code (PR heads, LLM-generated patches) in a constrained sandbox.

  systemd-run --user --scope   cgroup limits: memory, CPU, tasks, wall clock
  bwrap --unshare-all          new user/pid/net/ipc/uts namespaces → NO network (not even loopback services)
                               read-only /usr, /etc, and the target venv; the work copy is the only writable
                               bind; /tmp is a tmpfs; $HOME (gh token, ssh keys) is not mounted at all.

bwrap needs unprivileged user namespaces, which Ubuntu 24.04 restricts via AppArmor. deploy/root/
install-root.sh installs an AppArmor profile for a dedicated bwrap copy at /usr/local/lib/flect/bwrap.
Until then `available()` is False and callers must not execute untrusted code at all.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass


@dataclass
class SandboxResult:
    ok: bool
    returncode: int | None
    output: str
    timed_out: bool = False


class Sandbox:
    def __init__(self, cfg: dict):
        self.bwrap = cfg["bwrap"]
        self.memory_max = cfg["memory_max"]
        self.cpu_quota = cfg["cpu_quota"]
        self.tasks_max = int(cfg["tasks_max"])
        self.runtime_max_s = int(cfg["runtime_max_s"])

    def available(self) -> tuple[bool, str]:
        if not os.path.exists(self.bwrap):
            return False, f"{self.bwrap} missing (run deploy/root/install-root.sh)"
        res = subprocess.run([self.bwrap, "--unshare-all", "--ro-bind", "/", "/", "--proc", "/proc",
                              "--dev", "/dev", "true"], capture_output=True, text=True, timeout=20, check=False)
        if res.returncode != 0:
            return False, f"bwrap cannot create namespaces: {res.stderr.strip()[:200]}"
        return True, "ok"

    def command(self, workdir: str, argv: list[str], ro_binds: list[str]) -> list[str]:
        scope = ["systemd-run", "--user", "--scope", "--quiet", "--collect",
                 "-p", f"MemoryMax={self.memory_max}", "-p", "MemorySwapMax=0",
                 "-p", f"CPUQuota={self.cpu_quota}", "-p", f"TasksMax={self.tasks_max}",
                 "-p", f"RuntimeMaxSec={self.runtime_max_s}", "--"]
        box = [self.bwrap, "--unshare-all", "--die-with-parent", "--new-session",
               "--ro-bind", "/usr", "/usr", "--ro-bind", "/etc", "/etc",
               "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib", "--symlink", "usr/sbin", "/sbin",
               "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
               "--clearenv", "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "HOME", "/tmp",
               "--setenv", "PYTHONDONTWRITEBYTECODE", "1", "--setenv", "LANG", "C.UTF-8"]
        for path in ro_binds:
            box += ["--ro-bind", path, path]
        box += ["--bind", workdir, "/work", "--chdir", "/work"]
        return scope + box + argv

    def run(self, workdir: str, argv: list[str], ro_binds: list[str] | None = None) -> SandboxResult:
        ok, why = self.available()
        if not ok:
            return SandboxResult(False, None, f"sandbox unavailable: {why}")
        cmd = self.command(workdir, argv, ro_binds or [])
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=self.runtime_max_s + 30, check=False)
        except subprocess.TimeoutExpired as exc:
            return SandboxResult(False, None, (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "", True)
        out = (res.stdout + "\n" + res.stderr)[-12000:]
        return SandboxResult(res.returncode == 0, res.returncode, out)
