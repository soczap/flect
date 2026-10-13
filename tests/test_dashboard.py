"""Dashboard API: read-only endpoints the redesigned UI depends on."""
import re
from types import SimpleNamespace

from fastapi.testclient import TestClient

from flect.server import build_app


def client(cfg, db, live=None):
    return TestClient(build_app(db, cfg, None, live=live))


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


def test_dashboard_has_no_write_endpoints(cfg, db):
    app = build_app(db, cfg)
    methods = {m for r in app.routes for m in getattr(r, "methods", set())}
    assert methods <= {"GET", "HEAD"}
