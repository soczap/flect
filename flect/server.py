"""Read-only dashboard on 127.0.0.1. No endpoint changes state; use the `flect` CLI for that."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

from flect.config import CAPABILITIES

STATIC = Path(__file__).with_name("static")


def build_app(db, cfg, engine=None) -> FastAPI:
    app = FastAPI(title="Flect", docs_url=None, redoc_url=None, openapi_url=None)

    def modes():
        if engine:
            return {c: engine.mode(c) for c in CAPABILITIES}
        return {c: db.get(f"mode:{c}") or cfg.mode(c) for c in CAPABILITIES}

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/status")
    def status():
        return {"modes": modes(), "writes_paused": db.get("writes_paused"),
                "capabilities": db.get("status:capabilities"), "health": db.get("health:prod"),
                "dos": db.get("dos:snapshot"), "target": cfg["target"]["name"], "repo": cfg["github"]["repo"],
                "lkg": db.one("SELECT sha, started_ts FROM deployments WHERE env='prod' AND state='lkg' ORDER BY id DESC LIMIT 1")}

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

    @app.get("/api/reports")
    def reports():
        return db.all("SELECT id,kind,ref_sha,pr_number,max_severity,created_ts FROM reports ORDER BY id DESC LIMIT 100")

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
