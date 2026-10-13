"""Health probes for a target service: HTTP health endpoint and systemd --user unit state."""
from __future__ import annotations

import http.client
import ssl
import subprocess
import time
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass
class Probe:
    ts: float
    http_ok: bool
    http_status: int | None
    latency_ms: float | None
    error: str | None
    active_state: str | None
    n_restarts: int | None
    main_pid: int | None


def http_health(url: str, path: str, timeout: float = 4.0) -> tuple[bool, int | None, float | None, str | None]:
    """GET <url><path> on loopback; TLS certificate verification is off (self-signed, loopback only)."""
    parts = urlsplit(url)
    host, port = parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("health probes are loopback-only")
    started = time.monotonic()
    try:
        if parts.scheme == "https":
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            conn.request("GET", path, headers={"User-Agent": "flect-health/0.1"})
            resp = conn.getresponse()
            body = resp.read(4096)
        finally:
            conn.close()
        latency = (time.monotonic() - started) * 1000
        ok = resp.status == 200 and b'"ok"' in body
        return ok, resp.status, latency, None if ok else f"status {resp.status}"
    except Exception as exc:  # noqa: BLE001
        return False, None, None, f"{type(exc).__name__}: {exc}"[:200]


def unit_state(unit: str) -> tuple[str | None, int | None, int | None]:
    try:
        out = subprocess.run(["systemctl", "--user", "show", unit, "-p", "ActiveState,NRestarts,MainPID"],
                             capture_output=True, text=True, timeout=10, check=False).stdout
    except Exception:  # noqa: BLE001
        return None, None, None
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    def as_int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    return props.get("ActiveState"), as_int(props.get("NRestarts")), as_int(props.get("MainPID"))


def probe(url: str, path: str, unit: str) -> Probe:
    ok, status, latency, err = http_health(url, path)
    state, restarts, pid = unit_state(unit)
    return Probe(time.time(), ok, status, latency, err, state, restarts, pid)
