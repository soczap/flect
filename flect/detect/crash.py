"""Crash detection and classification for the production service.

Severity:
  S1  service down: health failing N consecutive probes, unit not active, or a restart loop
  S2  a code path keeps crashing: the same exception signature >= error_burst_count times in the window
Classification:
  code         traceback frames in the application package and no environment marker
  environment  disk/memory/port/permission/dependency-service problems — fixed by operators, not code
  unknown      no traceback available
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field

FRAME_RE = re.compile(r'File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>\S+)')
EXC_RE = re.compile(r"^(?P<type>[A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning)|KeyError|StopIteration)\b:?(?P<msg>.*)$",
                    re.M)
ENV_MARKERS = [
    (re.compile(r"No space left on device|ENOSPC"), "disk_full"),
    (re.compile(r"\bMemoryError\b|CUDA out of memory|OutOfMemoryError|Cannot allocate memory"), "out_of_memory"),
    (re.compile(r"Address already in use|EADDRINUSE"), "port_in_use"),
    (re.compile(r"PermissionError|Permission denied"), "permission"),
    (re.compile(r"ConnectionRefusedError|ConnectError|Connection refused|Name or service not known"), "dependency_unreachable"),
    (re.compile(r"ModuleNotFoundError|ImportError: (?:cannot|No module)"), "missing_dependency"),
    (re.compile(r"database is locked|disk I/O error"), "database"),
    (re.compile(r"certificate (?:has expired|verify failed)"), "certificate"),
]


@dataclass
class Traceback:
    text: str
    exc_type: str | None
    exc_msg: str
    frames: list[dict]
    app_frames: list[dict]
    signature: str
    env_marker: str | None


@dataclass
class CrashEvent:
    severity: str                  # S1 | S2
    reason: str
    classification: str            # code | environment | unknown
    traceback: Traceback | None
    evidence: dict = field(default_factory=dict)


def parse_traceback(text: str, app_dir: str, package: str = "vigil") -> Traceback | None:
    if "Traceback (most recent call last)" not in text and not FRAME_RE.search(text):
        return None
    frames = [{"file": m["file"], "line": int(m["line"]), "func": m["func"]} for m in FRAME_RE.finditer(text)]
    app_frames = []
    for f in frames:
        path = f["file"]
        rel = None
        if path.startswith(app_dir.rstrip("/") + "/"):
            rel = path[len(app_dir.rstrip("/")) + 1:]
        elif f"/{package}/" in path and "site-packages" not in path:
            rel = path[path.index(f"/{package}/") + 1:]
        if rel and rel.startswith(package + "/") and "site-packages" not in path:
            app_frames.append({**f, "rel": rel})
    exc_type, exc_msg = None, ""
    for m in EXC_RE.finditer(text):
        exc_type, exc_msg = m["type"], m["msg"].strip()
    env = next((name for rx, name in ENV_MARKERS if rx.search(text)), None)
    anchor = app_frames[-1] if app_frames else (frames[-1] if frames else {})
    sig_src = f"{exc_type}|{anchor.get('rel') or anchor.get('file')}|{anchor.get('func')}"
    signature = hashlib.sha256(sig_src.encode()).hexdigest()[:16]
    return Traceback(text[-8000:], exc_type, exc_msg[:300], frames, app_frames, signature, env)


def classify(tb: Traceback | None) -> str:
    if tb is None:
        return "unknown"
    if tb.env_marker:
        return "environment"
    return "code" if tb.app_frames else "unknown"


class CrashDetector:
    def __init__(self, cfg: dict, app_dir: str):
        self.cfg = cfg
        self.app_dir = app_dir
        self.consecutive_failures = 0
        self.last_restarts: int | None = None
        self.restart_times: deque = deque()
        self.sig_times: dict[str, deque] = defaultdict(deque)
        self.last_tb: Traceback | None = None
        self.down = False
        self.stopped = False

    def observe_traceback(self, text: str, t: float) -> CrashEvent | None:
        tb = parse_traceback(text, self.app_dir)
        if tb is None:
            return None
        self.last_tb = tb
        q = self.sig_times[tb.signature]
        q.append(t)
        window = self.cfg["error_burst_window_s"]
        while q and q[0] < t - window:
            q.popleft()
        if len(q) == self.cfg["error_burst_count"]:   # fire once when the burst threshold is crossed
            return CrashEvent("S2", f"{tb.exc_type or 'error'} repeated {len(q)}x in {window}s",
                              classify(tb), tb, {"signature": tb.signature, "count": len(q)})
        return None

    def observe_probe(self, probe, t: float) -> CrashEvent | None:
        if probe.n_restarts is not None:
            if self.last_restarts is not None and probe.n_restarts > self.last_restarts:
                for _ in range(probe.n_restarts - self.last_restarts):
                    self.restart_times.append(t)
            self.last_restarts = probe.n_restarts
        window = self.cfg["restart_loop_window_s"]
        while self.restart_times and self.restart_times[0] < t - window:
            self.restart_times.popleft()

        # A cleanly stopped unit ("inactive") means an operator stopped it on purpose; with Restart=always a
        # crash shows up as activating/failed or a restart loop instead. Never fight a deliberate stop.
        if probe.active_state in ("inactive", "deactivating"):
            self.consecutive_failures = 0
            self.stopped = True
            return None
        if self.stopped and probe.http_ok:
            self.stopped = False
        self.consecutive_failures = 0 if probe.http_ok else self.consecutive_failures + 1
        if self.stopped:
            return None          # still starting back up after a deliberate stop
        reasons = []
        if self.consecutive_failures >= self.cfg["health_fail_probes"]:
            reasons.append(f"health failed {self.consecutive_failures} consecutive probes ({probe.error})")
        if probe.active_state not in (None, "active", "activating", "reloading"):
            reasons.append(f"unit state {probe.active_state}")
        if len(self.restart_times) >= self.cfg["restart_loop_count"]:
            reasons.append(f"{len(self.restart_times)} restarts in {window}s")
        if reasons and not self.down:
            self.down = True
            tb = self.last_tb
            return CrashEvent("S1", "; ".join(reasons), classify(tb), tb,
                              {"active_state": probe.active_state, "n_restarts": probe.n_restarts,
                               "http_status": probe.http_status, "error": probe.error})
        if not reasons and probe.http_ok:
            self.down = False
        return None
