"""Pre-production VAPT against the UAT instance — and only the UAT instance.

Checks (all read-only / non-destructive; GET requests only, no payloads):
  VA-SCOPE    hard scope guard: the target must equal the configured UAT origin on loopback
  VA-STATIC   full static scan of the release tree (vendored SOC scanner + Bandit), optional OSV
  VA-HTTP     security headers / cookie attributes on the UI root (SOC http_checks)
  VA-TLS      protocol version, certificate validity window, self-signed
  VA-AUTHZ    every GET route in /openapi.json without path parameters must reject anonymous access
              unless it is on the documented public allowlist
The model then writes an executive summary that may only cite finding IDs produced here.
"""
from __future__ import annotations

import http.client
import json
import socket
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlsplit

from flect.analyze.soc.scanner import scan_project
from flect.gateway.llm import P_VAPT, build_messages

PUBLIC_ROUTES = {"/api/health", "/api/auth/login", "/api/auth/logout", "/openapi.json", "/docs", "/redoc",
                 "/docs/oauth2-redirect", "/"}
SEV = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

SUMMARY_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["executive_summary", "priority_finding_ids", "release_recommendation"],
    "properties": {
        "executive_summary": {"type": "string", "maxLength": 1500},
        "priority_finding_ids": {"type": "array", "items": {"type": "string", "maxLength": 160}, "maxItems": 10},
        "release_recommendation": {"enum": ["ship", "ship_with_followups", "do_not_ship"]},
    },
}
SUMMARY_INSTRUCTIONS = (
    "You are summarising a pre-production security assessment for the person who will approve the release. "
    "Use only the FINDINGS provided; do not invent vulnerabilities. Explain in plain words what matters most, "
    "pick at most 10 finding IDs to prioritise, and recommend whether to ship."
)


class ScopeError(ValueError):
    pass


@dataclass
class VFinding:
    id: str
    check: str
    severity: str
    title: str
    detail: str
    location: str = ""
    remediation: str = ""


@dataclass
class VaptReport:
    target: str
    sha: str
    started: str
    findings: list[VFinding] = field(default_factory=list)
    coverage: list[dict] = field(default_factory=list)
    summary: dict | None = None

    def max_severity(self) -> str:
        return max((f.severity for f in self.findings), key=lambda s: SEV[s], default="info")

    def passed(self) -> bool:
        return SEV[self.max_severity()] < SEV["high"]


def enforce_scope(target: str, uat_url: str, prod_ports: list[int]) -> tuple[str, int]:
    t, u = urlsplit(target), urlsplit(uat_url)
    if (t.scheme, t.hostname, t.port) != (u.scheme, u.hostname, u.port):
        raise ScopeError(f"VAPT target {target!r} is not the configured UAT origin {uat_url!r}")
    if t.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise ScopeError("VAPT targets must be on loopback")
    if t.port in [p for p in prod_ports if p != u.port]:
        raise ScopeError(f"port {t.port} is a protected production port")
    return t.hostname, t.port


def _get(host: str, port: int, path: str, timeout: float = 8.0) -> tuple[int, dict, bytes]:
    ctx = ssl.create_default_context()
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE   # self-signed UAT cert; TLS is assessed separately
    conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
    try:
        conn.request("GET", path, headers={"User-Agent": "flect-vapt/0.1 (read-only)", "Accept": "application/json"})
        resp = conn.getresponse()
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read(512 * 1024)
    finally:
        conn.close()


def tls_check(host: str, port: int) -> list[VFinding]:
    out = []
    ctx = ssl.create_default_context()
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=8) as sock, ctx.wrap_socket(sock, server_hostname=host) as tls:
        version = tls.version()
        der = tls.getpeercert(binary_form=True)
    if version in {"TLSv1", "TLSv1.1", "SSLv3"}:
        out.append(VFinding("VA-TLS-001", "VA-TLS", "high", f"Outdated TLS protocol negotiated: {version}",
                            "Clients can negotiate a deprecated protocol.", f"{host}:{port}", "Allow TLS 1.2+ only."))
    try:
        strict = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=8) as s, strict.wrap_socket(s, server_hostname=host):
            pass
    except ssl.SSLCertVerificationError as exc:
        out.append(VFinding("VA-TLS-002", "VA-TLS", "low", "Certificate is not publicly trusted",
                            f"{exc.verify_message}. Expected for an internal service; browsers will warn.",
                            f"{host}:{port}", "Use an internal CA trusted by client devices."))
    from flect.sources.keys import _cert_not_after
    not_after = _cert_not_after(ssl.DER_cert_to_PEM_cert(der))
    if not_after:
        days = (not_after - datetime.now(timezone.utc)).days
        if days < 30:
            out.append(VFinding("VA-TLS-003", "VA-TLS", "high" if days < 7 else "medium",
                                f"Certificate expires in {days} days", f"notAfter {not_after.isoformat()}",
                                f"{host}:{port}", "Renew the certificate."))
    return out


def authz_sweep(host: str, port: int, public: set[str] = PUBLIC_ROUTES) -> tuple[list[VFinding], dict]:
    status, _, body = _get(host, port, "/openapi.json")
    if status != 200:
        return [], {"name": "authz_sweep", "status": "not_run", "detail": f"/openapi.json returned {status}"}
    spec = json.loads(body)
    findings, tested = [], 0
    for path, ops in sorted((spec.get("paths") or {}).items()):
        if "get" not in ops or "{" in path or path in public:
            continue
        tested += 1
        st, headers, resp_body = _get(host, port, path)
        if st in (401, 403):
            continue
        if st == 200:
            ctype = headers.get("content-type", "")
            findings.append(VFinding(f"VA-AUTHZ-001:{path}", "VA-AUTHZ", "high",
                                     f"Route answers anonymous requests: GET {path}",
                                     f"HTTP 200 without credentials ({ctype}, {len(resp_body)} bytes).",
                                     path, "Require authentication, or add the route to the public allowlist if it is intentionally public."))
        elif st >= 500:
            findings.append(VFinding(f"VA-ERR-001:{path}", "VA-AUTHZ", "medium",
                                     f"Route errors on anonymous request: GET {path} → {st}",
                                     "Server error instead of a clean 401; may leak details or indicate a crash path.",
                                     path, "Check authentication before any processing."))
    return findings, {"name": "authz_sweep", "status": "completed", "routes_tested": tested}


def static_scan(tree: str, osv: bool) -> tuple[list[VFinding], list[dict]]:
    result = scan_project(tree, "flect-vapt", "release", osv=osv)
    out = []
    for f in result["findings"]:
        if f.get("source_scope") == "test":
            continue
        loc = f.get("location") or {}
        where = f"{loc.get('path')}:{loc.get('line')}" if loc.get("line") else (loc.get("path") or "")
        out.append(VFinding(f"VA-STATIC:{f['rule_id']}:{where}", "VA-STATIC", f["severity"], f["title"],
                            f.get("description", "")[:400], where, f.get("remediation", "")[:300]))
    return out, result["coverage"]


def http_posture(host: str, port: int) -> tuple[list[VFinding], dict]:
    """Browser security headers and cookie attributes on the UI root (one GET)."""
    status, headers, _ = _get(host, port, "/")
    missing = []
    if "text/html" in headers.get("content-type", ""):
        for key in ("content-security-policy", "x-content-type-options", "referrer-policy"):
            if key not in headers:
                missing.append(key)
        if "x-frame-options" not in headers and "frame-ancestors" not in headers.get("content-security-policy", ""):
            missing.append("frame embedding protection")
    if "strict-transport-security" not in headers:
        missing.append("strict-transport-security")
    out = []
    if missing:
        out.append(VFinding("VA-HTTP-001", "VA-HTTP", "low", "Missing browser security headers",
                            "Missing on GET /: " + ", ".join(missing), "/",
                            "Add the headers in the application (e.g. a FastAPI middleware)."))
    return out, {"name": "http_posture", "status": "completed", "http_status": status}


async def run_vapt(target: str, uat_url: str, prod_ports: list[int], tree: str, sha: str,
                   gateway=None, osv: bool = False) -> VaptReport:
    import asyncio
    host, port = enforce_scope(target, uat_url, prod_ports)
    report = VaptReport(target, sha, datetime.now(timezone.utc).isoformat(timespec="seconds"))
    for name, fn in (("static", lambda: static_scan(tree, osv)), ("http", lambda: http_posture(host, port)),
                     ("tls", lambda: (tls_check(host, port), {"name": "tls", "status": "completed"})),
                     ("authz", lambda: authz_sweep(host, port))):
        try:
            findings, cov = await asyncio.to_thread(fn)
            report.findings += findings
            report.coverage += cov if isinstance(cov, list) else [cov]
        except Exception as exc:  # noqa: BLE001
            report.coverage.append({"name": name, "status": "failed", "detail": f"{type(exc).__name__}: {exc}"[:200]})
    report.findings.sort(key=lambda f: (-SEV[f.severity], f.id))
    if gateway is not None and report.findings:
        msgs = build_messages("vapt_summary", [f.__dict__ for f in report.findings[:60]],
                              {"target": "UAT", "sha": sha, "coverage": report.coverage}, {},
                              SUMMARY_INSTRUCTIONS, gateway.cfg["max_prompt_chars"]["vapt"])
        try:
            summary = await gateway.ask("vapt_summary", P_VAPT, msgs, SUMMARY_SCHEMA, ref=sha[:12])
            known = {f.id for f in report.findings}
            summary["priority_finding_ids"] = [i for i in summary["priority_finding_ids"] if i in known]
            report.summary = summary
        except Exception as exc:  # noqa: BLE001
            report.summary = {"executive_summary": f"(model summary unavailable: {exc})", "priority_finding_ids": [],
                              "release_recommendation": "ship_with_followups" if report.passed() else "do_not_ship"}
    return report


def render(report: VaptReport) -> str:
    counts = {s: sum(f.severity == s for f in report.findings) for s in ("critical", "high", "medium", "low", "info")}
    verdict = "PASS" if report.passed() else "FAIL"
    lines = [f"## 🛡️ Flect VAPT report: {verdict}",
             f"Target: UAT `{report.target}` · commit `{report.sha[:12]}` · {report.started}", "",
             "| Critical | High | Medium | Low |", "|---|---|---|---|",
             f"| {counts['critical']} | {counts['high']} | {counts['medium']} | {counts['low']} |", ""]
    if report.summary:
        lines += ["### Summary", report.summary["executive_summary"], "",
                  f"**Recommendation:** {report.summary['release_recommendation'].replace('_', ' ')}", ""]
    if report.findings:
        lines += ["### Findings", "| ID | Severity | Title | Location | Fix |", "|---|---|---|---|---|"]
        for f in report.findings[:60]:
            lines.append(f"| `{f.id[:70]}` | {f.severity} | {f.title} | {f.location} | {f.remediation[:120]} |")
        lines.append("")
    lines += ["### Coverage"] + [f"- {c.get('name')}: {c.get('status')}" + (f" — {c['detail']}" if c.get('detail') else "")
                                  for c in report.coverage]
    lines += ["", "_Read-only assessment: GET requests only, no exploit payloads, UAT only. "
              "No findings does not prove the release is secure._"]
    return "\n".join(lines)
