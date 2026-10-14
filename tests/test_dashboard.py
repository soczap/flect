"""Dashboard API: read-only endpoints the redesigned UI depends on."""
import re
from types import SimpleNamespace

from fastapi.testclient import TestClient

from flect.server import build_app


def client(cfg, db, live=None):
    return TestClient(build_app(db, cfg, None, live=live), base_url="http://127.0.0.1:1113")


def test_index_stamps_assets_and_static_served(cfg, db):
    c = client(cfg, db)
    html = c.get("/").text
    assert re.search(r"/static/app\.js\?v=\d+", html) and re.search(r"/static/app\.css\?v=\d+", html)
    assert c.get("/static/app.js").status_code == 200 and c.get("/static/app.css").status_code == 200


def test_overview_and_history(cfg, db):
    live = SimpleNamespace(started=1.0, health_hist=[(100, True, 12.0), (105, False, None), (110, True, 18.0)],
                           traffic_hist=[(100, 0.4, 0.3, False)])
    db.open_incident("expiry", "critical", "frs-backend: failing", {})
    db.execute("INSERT INTO deployments(env,sha,trigger,state,started_ts) VALUES('prod','abc','rollback','healthy',datetime('now'))")
    c = client(cfg, db, live)
    o = c.get("/api/overview").json()
    assert o["open_incident_total"] == 1 and o["open_incidents"] == {"critical": 1}
    assert o["availability_1h"] == round(100 * 2 / 3, 2) and o["latency_ms_avg"] == 15.0
    assert o["had_failure_1h"] is True and o["healthy_since"] == 105 and o["rollbacks_24h"] == 1
    h = c.get("/api/history").json()
    assert len(h["health"]) == 3 and h["traffic"][0][1] == 0.4
    m = c.get("/api/meta").json()
    assert m["repo_url"] == "https://github.com/soczap/Computer_Vision"


def test_report_titles_and_path_confinement(cfg, db, tmp_path):
    from flect.actuators.notify import Notifier
    n = Notifier(db, cfg.data_dir / "reports")
    n.save_report("vapt", "x", "## 🛡️ Flect VAPT report: PASS\n\nbody", "a" * 40, None, "medium")
    c = client(cfg, db)
    rows = c.get("/api/reports").json()
    assert rows[0]["title"] == "Flect VAPT report: PASS" and "path" not in rows[0]
    assert "body" in c.get(f"/api/reports/{rows[0]['id']}").text
    outside = tmp_path / "secret.md"; outside.write_text("nope")
    db.execute("INSERT INTO reports(kind,path,created_ts) VALUES('vapt',?,datetime('now'))", (str(outside),))
    rid = db.one("SELECT MAX(id) id FROM reports")["id"]
    assert c.get(f"/api/reports/{rid}").status_code == 403


def test_only_flect_ai_endpoints_accept_writes(cfg, db):
    app = build_app(db, cfg)
    writes = {r.path for r in app.routes if getattr(r, "methods", set()) - {"GET", "HEAD"}}
    assert writes and all(p.startswith("/api/ai/") for p in writes)


def test_foreign_host_and_tokenless_writes_are_refused(cfg, db):
    c = client(cfg, db)
    assert c.get("/api/status").status_code == 200
    assert c.get("/api/status", headers={"host": "evil.example:1113"}).status_code == 403    # DNS rebinding
    assert c.get("/api/status", headers={"host": "[::1]:1113"}).status_code == 200
    token = c.get("/api/ai/session").json()["token"]
    assert c.post("/api/ai/actions/1/dismiss").status_code == 403                           # no token
    assert c.post("/api/ai/actions/1/dismiss", headers={"x-flect-token": "nope"}).status_code == 403
    assert c.post("/api/ai/actions/1/dismiss", headers={"x-flect-token": token,
                                                        "origin": "http://localhost:3000"}).status_code == 403
    # Past the guard: no assistant in this process.
    assert c.post("/api/ai/actions/1/dismiss", headers={"x-flect-token": token,
                                                        "origin": "http://127.0.0.1:1113"}).status_code == 503
