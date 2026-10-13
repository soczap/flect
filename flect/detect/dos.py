"""Deterministic DoS / DDoS detector over VIGIL access logs.

Rules (thresholds from config [dos]):
  DOS-RATE-001   one IP sustains > per_ip_rps for per_ip_sustain_s seconds
  DOS-AUTH-001   one IP produces > failed_logins_per_min failed logins (401/429 on /api/auth/login)
  DOS-SCAN-001   one IP gets > failed_paths_per_min distinct paths answered 400/403/404/405 in a minute
                 (scanners probe paths that do not exist; normal browsing is mostly 2xx/3xx)
  DOS-FLOOD-001  total request rate > global_flood_factor x its EWMA baseline (and > global_min_rps);
                 while flooding, per-IP thresholds are divided by 4 so the top talkers get caught.
No LLM in this path. The allowlist always wins.
"""
from __future__ import annotations

import ipaddress
from collections import defaultdict, deque
from dataclasses import dataclass

LOGIN_PATH = "/api/auth/login"
SCAN_STATUSES = {400, 403, 404, 405}


@dataclass
class BlockRequest:
    ip: str
    rule_id: str
    reason: str
    evidence: dict


class Allowlist:
    def __init__(self, cidrs: list[str]):
        self.nets = [ipaddress.ip_network(c, strict=False) for c in cidrs]

    def __contains__(self, ip: str) -> bool:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return True  # unparseable → never block
        if addr.version == 6 and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        return any(addr in n for n in self.nets)


class DosDetector:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.allow = Allowlist(cfg["allowlist"])
        self.hits: dict[str, deque] = defaultdict(deque)          # ip -> timestamps (60 s)
        self.fails: dict[str, deque] = defaultdict(deque)         # ip -> failed-login timestamps
        self.paths: dict[str, deque] = defaultdict(deque)         # ip -> (ts, path)
        self.total: deque = deque()                               # all request timestamps (10 s)
        self.ewma: float | None = None
        self.flooding = False
        self.flagged: dict[str, float] = {}                       # ip -> ts last flagged (debounce)
        self.ignored_allowlisted = 0

    # ── ingest ─────────────────────────────────────────────────────────────
    def observe(self, ip: str, path: str, method: str, status: int, t: float) -> None:
        self.total.append(t)
        if ip in self.allow:
            self.ignored_allowlisted += 1
            return
        self.hits[ip].append(t)
        if status in SCAN_STATUSES:
            self.paths[ip].append((t, path))
        if path == LOGIN_PATH and method == "POST" and status in (401, 429):
            self.fails[ip].append(t)

    # ── evaluate (call ~once per second) ───────────────────────────────────
    def tick(self, t: float) -> list[BlockRequest]:
        self._expire(t)
        out: list[BlockRequest] = []
        global_rps = len(self.total) / 10.0
        self._update_flood(global_rps)
        divisor = 4.0 if self.flooding else 1.0
        rps_limit = self.cfg["per_ip_rps"] / divisor
        sustain = self.cfg["per_ip_sustain_s"]
        for ip, q in list(self.hits.items()):
            if self.flagged.get(ip, 0) > t - 60:
                continue
            recent = [x for x in q if x > t - sustain]
            rate = len(recent) / sustain
            if rate > rps_limit and recent and (recent[-1] - recent[0]) >= sustain * 0.8:
                rule = "DOS-FLOOD-001" if self.flooding else "DOS-RATE-001"
                out.append(self._flag(ip, rule, f"{rate:.1f} req/s sustained over {sustain}s "
                                      f"(limit {rps_limit:.1f}{', flood mode' if self.flooding else ''})",
                                      {"rate": round(rate, 2), "limit": rps_limit, "global_rps": round(global_rps, 1)}, t))
                continue
            fails = len(self.fails.get(ip, ()))
            if fails > self.cfg["failed_logins_per_min"] / divisor:
                out.append(self._flag(ip, "DOS-AUTH-001", f"{fails} failed logins in 60s",
                                      {"failed_logins": fails}, t))
                continue
            distinct = len({p for _, p in self.paths.get(ip, ())})
            if distinct > self.cfg["failed_paths_per_min"] / divisor:
                out.append(self._flag(ip, "DOS-SCAN-001", f"{distinct} distinct failed paths (4xx) in 60s",
                                      {"failed_distinct_paths": distinct}, t))
        return out

    def snapshot(self, top: int = 10) -> dict:
        talkers = sorted(((ip, len(q)) for ip, q in self.hits.items()), key=lambda x: -x[1])[:top]
        return {"global_rps": round(len(self.total) / 10.0, 2), "baseline_rps": round(self.ewma or 0, 2),
                "flooding": self.flooding, "top_talkers_60s": talkers,
                "allowlisted_requests": self.ignored_allowlisted}

    # ── internals ──────────────────────────────────────────────────────────
    def _flag(self, ip, rule, reason, evidence, t) -> BlockRequest:
        self.flagged[ip] = t
        return BlockRequest(ip, rule, reason, evidence)

    def _update_flood(self, rps: float) -> None:
        if self.ewma is None:
            self.ewma = rps
            return
        factor, floor = self.cfg["global_flood_factor"], self.cfg["global_min_rps"]
        self.flooding = rps > floor and rps > factor * max(self.ewma, 1.0)
        if not self.flooding:  # do not let an attack poison the baseline
            self.ewma = 0.98 * self.ewma + 0.02 * rps

    def _expire(self, t: float) -> None:
        while self.total and self.total[0] < t - 10:
            self.total.popleft()
        for table in (self.hits, self.fails):
            for ip in list(table):
                q = table[ip]
                while q and q[0] < t - 60:
                    q.popleft()
                if not q:
                    del table[ip]
        for ip in list(self.paths):
            q = self.paths[ip]
            while q and q[0][0] < t - 60:
                q.popleft()
            if not q:
                del self.paths[ip]
        for ip in [ip for ip, ts in self.flagged.items() if ts < t - 3600]:
            del self.flagged[ip]
