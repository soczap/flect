"""Read-only dashboard on 127.0.0.1. No endpoint changes state; use the `flect` CLI for that."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from flect import __version__
from flect.config import CAPABILITIES

STATIC = Path(__file__).with_name("static")


def build_app(db, cfg, engine=None, live=None) -> FastAPI:
    app = FastAPI(title="Flect", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def since(hours: float) -> str:
        return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")

    def modes():
        if engine:
            return {c: engine.mode(c) for c in CAPABILITIES}
        return {c: db.get(f"mode:{c}") or cfg.mode(c) for c in CAPABILITIES}

    @app.get("/", response_class=HTMLResponse)
    def index():
        # Version-stamp the assets so browsers never run a stale UI after an update.
        stamp = int(max((STATIC / f).stat().st_mtime for f in ("app.js", "app.css")))
        html = (STATIC / "index.html").read_text()
        return html.replace("/static/app.js", f"/static/app.js?v={stamp}").replace("/static/app.css", f"/static/app.css?v={stamp}")

    @app.get("/api/status")
    def status():
        return {"modes": modes(), "writes_paused": db.get("writes_paused"),
                "capabilities": db.get("status:capabilities"), "health": db.get("health:prod"),
                "dos": db.get("dos:snapshot"), "target": cfg["target"]["name"], "repo": cfg["github"]["repo"],
                "lkg": db.one("SELECT sha, started_ts FROM deployments WHERE env='prod' AND state='lkg' ORDER BY id DESC LIMIT 1")}

    @app.get("/api/meta")
    def meta():
        repo = cfg["github"]["repo"]
        return {"version": __version__, "repo": repo, "repo_url": f"https://github.com/{repo}",
                "target": cfg["target"]["name"], "prod_url": cfg["target"]["prod_url"],
                "uat_url": cfg["target"]["uat_url"], "feature_base": cfg["github"]["feature_base"],
                "prod_branch": cfg["github"]["prod_branch"], "started": getattr(live, "started", None),
                "allowlist": cfg["dos"]["allowlist"], "dashboard": cfg["dashboard"]}

    @app.get("/api/overview")
    def overview():
        day = since(24)
        inc = db.all("SELECT severity, COUNT(*) n FROM incidents WHERE state!='resolved' GROUP BY severity")
        llm = db.one("SELECT COUNT(*) calls, SUM(status='ok') ok, AVG((julianday(finished_ts)-julianday(started_ts))*86400) "
                     "avg_s, SUM(completion_tokens) out_tokens FROM llm_calls WHERE queued_ts > ?", (day,))
        hist = list(getattr(live, "health_hist", []))
        ok_pts = [h for h in hist if h[1]]
        last_fail = max((h[0] for h in hist if not h[1]), default=None)
        return {
            "open_incidents": {r["severity"]: r["n"] for r in inc},
            "open_incident_total": sum(r["n"] for r in inc),
            "resolved_24h": (db.one("SELECT COUNT(*) n FROM incidents WHERE state='resolved' AND closed_ts > ?", (day,)) or {}).get("n", 0),
            "active_blocks": (db.one("SELECT COUNT(*) n FROM blocks WHERE active=1 AND expires_ts > ?", (since(0),)) or {}).get("n", 0),
            "blocks_24h": (db.one("SELECT COUNT(*) n FROM blocks WHERE created_ts > ?", (day,)) or {}).get("n", 0),
            "prs": {r["state"]: r["n"] for r in db.all("SELECT state, COUNT(*) n FROM prs GROUP BY state")},
            "deploys_24h": (db.one("SELECT COUNT(*) n FROM deployments WHERE started_ts > ?", (day,)) or {}).get("n", 0),
            "last_deploy": db.one("SELECT env, sha, trigger, state, started_ts FROM deployments ORDER BY id DESC LIMIT 1"),
            "keys": {r["alert_level"]: r["n"] for r in db.all("SELECT alert_level, COUNT(*) n FROM keys GROUP BY alert_level")},
            "next_expiry": db.one("SELECT name, expires_ts, days_left FROM keys WHERE days_left IS NOT NULL ORDER BY days_left LIMIT 1"),
            "llm_24h": llm,
            "availability_1h": round(100 * len(ok_pts) / len(hist), 2) if hist else None,
            "latency_ms_avg": round(sum(h[2] for h in ok_pts if h[2]) / max(1, len([h for h in ok_pts if h[2]])), 1) if ok_pts else None,
            "healthy_since": (last_fail if last_fail else (hist[0][0] if hist else None)),
            "actions_24h": (db.one("SELECT COUNT(*) n FROM actions WHERE ts > ?", (day,)) or {}).get("n", 0),
            "reports": (db.one("SELECT COUNT(*) n FROM reports") or {}).get("n", 0),
            "reports_by_kind": {r["kind"]: r["n"] for r in db.all("SELECT kind, COUNT(*) n FROM reports GROUP BY kind")},
            "rollbacks_24h": (db.one("SELECT COUNT(*) n FROM deployments WHERE trigger='rollback' AND started_ts > ?", (day,)) or {}).get("n", 0),
            "had_failure_1h": bool(last_fail),
            "now": time.time(),
        }

    @app.get("/api/history")
    def history():
        return {"health": list(getattr(live, "health_hist", [])), "traffic": list(getattr(live, "traffic_hist", []))}

    @app.get("/api/incidents")
    def incidents(limit: int = 50):
        rows = db.all("SELECT id,kind,severity,state,opened_ts,closed_ts,title,summary,github_issue,llm_summary "
                      "FROM incidents ORDER BY id DESC LIMIT ?", (min(limit, 500),))
        return rows

    @app.get("/api/incidents/{incident_id}")
    def incident(incident_id: int):
        row = db.one("SELECT * FROM incidents WHERE id=?", (incident_id,))
        if not row:
            raise HTTPException(404)
        row["details"] = json.loads(row["details"] or "{}")
        row["actions"] = db.all("SELECT ts,decision,target,mode,ok,result FROM actions WHERE incident_id=? ORDER BY id",
                                (incident_id,))
        return row

    @app.get("/api/blocks")
    def blocks(active_only: bool = False):
        q = "SELECT * FROM blocks" + (" WHERE active=1" if active_only else "") + " ORDER BY id DESC LIMIT 200"
        return db.all(q)

    @app.get("/api/prs")
    def prs():
        return db.all("SELECT number,head_sha,base,kind,state,risk,title,statuses,updated_ts FROM prs "
                      "ORDER BY updated_ts DESC LIMIT 100")

    @app.get("/api/deployments")
    def deployments():
        return db.all("SELECT * FROM deployments ORDER BY id DESC LIMIT 100")

    @app.get("/api/keys")
    def keys():
        return db.all("SELECT name,kind,location,expires_ts,days_left,last_probe_ts,last_probe_ok,alert_level,details "
                      "FROM keys ORDER BY COALESCE(days_left, 1e9)")

    @app.get("/api/actions")
    def actions(limit: int = 100):
        return db.all("SELECT id,ts,decision,target,params,mode,ok,result,incident_id FROM actions ORDER BY id DESC LIMIT ?",
                      (min(limit, 1000),))

    @app.get("/api/llm")
    def llm():
        return db.all("SELECT id,task,priority,ref,queued_ts,started_ts,finished_ts,prompt_tokens,completion_tokens,"
                      "status,error FROM llm_calls ORDER BY id DESC LIMIT 50")

    def report_title(path: str) -> str:
        """First heading of the report, without markdown/emoji noise."""
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        return "".join(ch for ch in line.lstrip("#").strip() if ch.isprintable() and ord(ch) < 0x2000).strip()[:160]
        except OSError:
            pass
        return ""

    @app.get("/api/reports")
    def reports():
        rows = db.all("SELECT id,kind,ref_sha,pr_number,max_severity,created_ts,path FROM reports ORDER BY id DESC LIMIT 200")
        for r in rows:
            r["title"] = report_title(r.pop("path"))
        return rows

    @app.get("/api/reports/{report_id}", response_class=PlainTextResponse)
    def report(report_id: int):
        row = db.one("SELECT path FROM reports WHERE id=?", (report_id,))
        if not row:
            raise HTTPException(404)
        path = Path(row["path"]).resolve()
        if not path.is_relative_to((cfg.data_dir / "reports").resolve()):
            raise HTTPException(403)
        return path.read_text()

    @app.get("/api/audit/verify")
    def audit_verify():
        return {"chain_ok": db.verify_audit_chain()}

    return app
