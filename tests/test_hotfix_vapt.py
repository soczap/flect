import http.server
import json
import ssl
import subprocess
import threading

import pytest

from flect.analyze import vapt
from flect.analyze.hotfix import check_limits

DIFF = "--- a/vigil/api/x.py\n+++ b/vigil/api/x.py\n@@ -1 +1 @@\n-a\n+b\n"


def proposal(**kw):
    p = {"classification": "code", "diagnosis": "d", "root_cause_file": "vigil/api/x.py", "confidence": "high",
         "patch_unified_diff": DIFF, "regression_test_path": "tests/test_flect_x.py", "regression_test_code": "def test(): pass"}
    p.update(kw)
    return p


def test_hotfix_limits(cfg):
    c = cfg["crash"]
    assert check_limits(proposal(), c) is None
    assert "environment" in check_limits(proposal(classification="environment"), c)
    assert check_limits(proposal(patch_unified_diff=""), c) == "empty patch"
    bad = DIFF.replace("vigil/api/x.py", "vigil/api/auth.py")
    assert "forbidden" in check_limits(proposal(patch_unified_diff=bad), c)
    assert "existing tests" in check_limits(proposal(patch_unified_diff=DIFF.replace("vigil/api/x.py", "tests/test_a.py")), c)
    big = "--- a/vigil/a.py\n+++ b/vigil/a.py\n@@ -1,300 +1,300 @@\n" + "-x\n+y\n" * 150
    assert "lines" in check_limits(proposal(patch_unified_diff=big), c)
    assert "unsafe" in check_limits(proposal(patch_unified_diff=DIFF.replace("vigil/api/x.py", "../etc/passwd")), c)


def test_vapt_scope_guard():
    uat = "https://127.0.0.1:8190"
    assert vapt.enforce_scope(uat, uat, [8090, 8190]) == ("127.0.0.1", 8190)
    for bad in ("https://127.0.0.1:8090", "https://192.168.7.8:8190", "http://127.0.0.1:8190", "https://example.com:8190"):
        with pytest.raises(vapt.ScopeError):
            vapt.enforce_scope(bad, uat, [8090, 8190])


@pytest.fixture
def https_app(tmp_path):
    cert, key = tmp_path / "c.pem", tmp_path / "k.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert),
                    "-days", "2", "-subj", "/CN=127.0.0.1"], check=True, capture_output=True)
    spec = {"paths": {"/api/health": {"get": {}}, "/api/events": {"get": {}}, "/api/leaky": {"get": {}},
                      "/api/broken": {"get": {}}, "/api/items/{id}": {"get": {}}, "/api/write": {"post": {}}}}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            routes = {"/openapi.json": (200, json.dumps(spec)), "/api/health": (200, '{"status":"ok"}'),
                      "/api/events": (401, "{}"), "/api/leaky": (200, "[1,2,3]"), "/api/broken": (500, "boom"),
                      "/": (200, "<html></html>")}
            code, body = routes.get(self.path, (404, ""))
            self.send_response(code)
            self.send_header("Content-Type", "text/html" if self.path == "/" else "application/json")
            self.end_headers()
            self.wfile.write(body.encode())

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


def test_authz_sweep_and_tls(https_app):
    port = https_app
    findings, cov = vapt.authz_sweep("127.0.0.1", port)
    ids = sorted(f.id for f in findings)
    assert ids == ["VA-AUTHZ-001:/api/leaky", "VA-ERR-001:/api/broken"]
    assert cov["routes_tested"] == 3              # health public, {id} and POST skipped
    tls = {f.id: f for f in vapt.tls_check("127.0.0.1", port)}
    assert "VA-TLS-002" in tls and tls["VA-TLS-003"].severity == "high"   # self-signed, expires in 2 days
    hdr, _ = vapt.http_posture("127.0.0.1", port)
    assert hdr and "content-security-policy" in hdr[0].detail


def test_full_vapt_report(https_app, tmp_path):
    import asyncio
    (tmp_path / "tree").mkdir()
    (tmp_path / "tree" / "app.py").write_text("def f():\n    return 1\n")
    url = f"https://127.0.0.1:{https_app}"
    report = asyncio.run(vapt.run_vapt(url, url, [8090, https_app], str(tmp_path / "tree"), "c" * 40))
    assert not report.passed()                     # anonymous data route is high
    md = vapt.render(report)
    assert "VA-AUTHZ-001:/api/leaky" in md and "FAIL" in md


def test_tooling_findings_are_capped(tmp_path):
    (tmp_path / "scripts").mkdir(); (tmp_path / "vigil").mkdir()
    (tmp_path / "scripts" / "ops.py").write_text("import os\ndef f(c):\n    os.system(c)\n")
    (tmp_path / "vigil" / "api.py").write_text("import os\ndef f(c):\n    os.system(c)\n")
    findings, cov = vapt.static_scan(str(tmp_path), False)
    sev = {f.location.split(":")[0]: f.severity for f in findings if "PY-SHELL" in f.id}
    assert sev == {"scripts/ops.py": "low", "vigil/api.py": "high"}
    assert all(c["name"] not in ("http_posture", "authenticated_testing") for c in cov)
