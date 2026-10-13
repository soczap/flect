"""Key / token / certificate expiry and liveness checks. Secret values never leave this module."""
from __future__ import annotations

import base64
import json
import re
import socket
import ssl
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from flect.redact import register_secret
from flect.sources.health import http_health

JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.([A-Za-z0-9_-]+)\.[A-Za-z0-9_-]+\b")


@dataclass
class KeyStatus:
    name: str
    kind: str
    location: str
    expires: datetime | None = None
    probe_ok: bool | None = None
    details: str = ""

    def days_left(self, now: datetime | None = None) -> float | None:
        if not self.expires:
            return None
        now = now or datetime.now(timezone.utc)
        return round((self.expires - now).total_seconds() / 86400, 2)


def alert_level(days_left: float | None, warn_days: list[int], probe_ok: bool | None) -> str:
    if probe_ok is False:
        return "failing"
    if days_left is None:
        return "ok"
    if days_left <= 0:
        return "expired"
    for d in sorted(warn_days):
        if days_left <= d:
            return f"T-{d}d"
    return "ok"


def parse_github_expiry(headers_text: str) -> datetime | None:
    m = re.search(r"(?im)^github-authentication-token-expiration:\s*(.+?)\s*$", headers_text)
    if not m:
        return None
    raw = m.group(1).replace(" UTC", "+00:00")
    for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M:%S %z"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def github_pat(runner=subprocess.run) -> KeyStatus:
    st = KeyStatus("github-pat (gh, soczap)", "github_pat", "gh auth (hosts.yml)")
    try:
        res = runner(["gh", "api", "-i", "user"], capture_output=True, text=True, timeout=30, check=False)
    except Exception as exc:  # noqa: BLE001
        st.probe_ok, st.details = False, f"gh failed: {type(exc).__name__}"
        return st
    head, _, body = res.stdout.partition("\r\n\r\n") if "\r\n\r\n" in res.stdout else res.stdout.partition("\n\n")
    st.expires = parse_github_expiry(head)
    status = re.search(r"HTTP/\S+\s+(\d{3})", head)
    st.probe_ok = bool(status and status.group(1) == "200")
    try:
        login = json.loads(body).get("login")
        st.details = f"login={login}" + ("" if st.expires else "; token has no expiry header")
    except (json.JSONDecodeError, AttributeError):
        st.details = f"gh api exit {res.returncode}"
    return st


def _cert_not_after(pem: str) -> datetime | None:
    res = subprocess.run(["openssl", "x509", "-noout", "-enddate"], input=pem, capture_output=True,
                         text=True, timeout=10, check=False)
    m = re.search(r"notAfter=(.+)", res.stdout)
    if not m:
        return None
    return datetime.strptime(m.group(1).strip(), "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)


def tls_cert_file(path: str) -> KeyStatus:
    st = KeyStatus(f"tls-cert {Path(path).name}", "tls_cert", path)
    try:
        st.expires = _cert_not_after(Path(path).read_text())
        st.probe_ok = st.expires is not None
    except OSError as exc:
        st.probe_ok, st.details = False, f"unreadable: {type(exc).__name__}"
    return st


def tls_cert_endpoint(host: str, port: int) -> KeyStatus:
    st = KeyStatus(f"tls-endpoint {host}:{port}", "tls_cert", f"{host}:{port}")
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        with socket.create_connection((host, port), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                der = tls.getpeercert(binary_form=True)
        st.expires = _cert_not_after(ssl.DER_cert_to_PEM_cert(der))
        st.probe_ok = True
    except Exception as exc:  # noqa: BLE001
        st.probe_ok, st.details = False, f"{type(exc).__name__}"
    return st


def jwt_in_env_file(path: str) -> list[KeyStatus]:
    """Find JWT-shaped values in an env file and report their `exp`. Values are registered for redaction."""
    out = []
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        name, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        register_secret(value)
        m = JWT_RE.search(value)
        if not m:
            continue
        st = KeyStatus(f"jwt {name.strip()}", "jwt", f"{path}:{name.strip()}")
        try:
            payload = json.loads(base64.urlsafe_b64decode(m.group(1) + "=" * (-len(m.group(1)) % 4)))
            if "exp" in payload:
                st.expires = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)
            st.probe_ok = True
        except (ValueError, TypeError):
            st.probe_ok, st.details = False, "undecodable JWT"
        out.append(st)
    return out


def service_liveness(name: str, url: str, path: str) -> KeyStatus:
    st = KeyStatus(name, "service", url + path)
    if url.startswith("https://") or url.startswith("http://"):
        ok, status, _, err = http_health(url, path) if path.endswith("health") else _any_http(url, path)
        st.probe_ok, st.details = ok, err or (f"status {status}" if status else "")
    return st


def _any_http(url: str, path: str):
    ok, status, latency, err = http_health(url, path)
    # Any HTTP answer (even 401/404) proves the service is up; credentials are judged separately.
    alive = status is not None and status < 500
    return alive, status, latency, None if alive else err


def _env_value(path: str, key: str) -> str | None:
    """Read one non-secret setting (e.g. a URL) from an env file."""
    try:
        for line in Path(path).read_text().splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def run_all(cfg) -> list[KeyStatus]:
    target = cfg["target"]
    results = [github_pat()]
    results += [tls_cert_file(p) for p in target.get("tls_certs", [])]
    results.append(tls_cert_endpoint("127.0.0.1", 8090))
    results += jwt_in_env_file(str(Path(target["prod_dir"]) / ".env"))
    results.append(service_liveness("llama-server", "http://127.0.0.1:1111", "/health"))
    results.append(service_liveness("ollama", "http://127.0.0.1:11434", "/api/tags"))
    frs_url = _env_value(str(Path(target["prod_dir"]) / ".env"), "VIGIL_FRS_URL") or "https://127.0.0.1:8000"
    if urlsplit(frs_url).hostname in {"127.0.0.1", "localhost", "::1"}:
        frs = service_liveness("frs-backend", frs_url.rstrip("/"), "/")
        if frs.probe_ok is False:
            frs.details = f"VIGIL_FRS_URL={frs_url} unreachable: {frs.details}"
        results.append(frs)
    for extra in cfg["keys"].get("extra", []):
        results.append(service_liveness(extra["name"], extra["url"], extra.get("path", "/")))
    return results
