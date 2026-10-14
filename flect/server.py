"""Dashboard on 127.0.0.1.

Everything is read-only except the Flect AI console (/api/ai/*), where the operator talks to Flect and approves
the actions it suggests. Those write endpoints need the per-start session token from /api/ai/session and a
same-origin request; every request must also name a loopback host, which blocks DNS-rebinding pages.
"""
from __future__ import annotations

import hmac
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from flect import __version__
from flect.config import CAPABILITIES

STATIC = Path(__file__).with_name("static")
SAFE_METHODS = {"GET", "HEAD"}


def host_name(value: str) -> str:
    """'localhost:1113' → 'localhost', '[::1]:1113' → '::1'."""
    value = (value or "").strip().lower()
    if value.startswith("["):
        return value[1:value.find("]")] if "]" in value else value
    return value.split(":")[0]


class LoopbackGuard:
    """ASGI middleware: refuse foreign Host names, and writes without the session token or from another origin."""

    def __init__(self, app, allowed: set[str], token: str):
        self.app, self.allowed, self.token = app, allowed, token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        host = headers.get("host", "")
        why = None
        if host_name(host) not in self.allowed:
            why = "Flect answers only on its loopback address."
        elif scope["method"] not in SAFE_METHODS:
            origin = headers.get("origin")
            if origin and urlsplit(origin).netloc.lower() != host.lower():
                why = "Cross-origin request refused."
            elif not hmac.compare_digest(headers.get("x-flect-token", ""), self.token):
                why = "Missing or stale Flect session token. Reload the page."
        if why:
            return await PlainTextResponse(why, status_code=403)(scope, receive, send)
        return await self.app(scope, receive, send)


def build_app(db, cfg, engine=None, live=None) -> FastAPI:
    app = FastAPI(title="Flect", docs_url=None, redoc_url=None, openapi_url=None)
    token = secrets.token_urlsafe(32)
    allowed = {h.lower() for h in cfg["dashboard"].get("allowed_hosts", ["127.0.0.1", "localhost", "::1"])}
    app.add_middleware(LoopbackGuard, allowed=allowed, token=token)
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
            "ai_pending": (db.one("SELECT COUNT(*) n FROM ai_actions WHERE state='proposed' AND created_ts > ?",
                                  (since(cfg["ai"]["proposal_ttl_min"] / 60),)) or {}).get("n", 0),
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

    # ── Flect AI console ───────────────────────────────────────────────────
    def assistant():
        a = getattr(live, "ai", None)
        if a is None:
            raise HTTPException(503, "Flect AI is not running in this process")
        return a

    def local(body: dict) -> dict:
        return {"local_time": str(body.get("local_time") or "")[:80], "tz": str(body.get("tz") or "")[:64]}

    def stream(queue) -> StreamingResponse:
        """Newline-delimited JSON events until 'done'. If the browser goes away the turn still completes."""
        async def events():
            while True:
                ev = await queue.get()
                yield json.dumps(ev, default=str) + "\n"
                if ev.get("type") == "done":
                    return
        return StreamingResponse(events(), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    async def body_of(request: Request) -> dict:
        try:
            body = await request.json()
        except ValueError:
            body = {}
        return body if isinstance(body, dict) else {}

    @app.get("/api/ai/session")
    def ai_session():
        a = getattr(live, "ai", None)
        return {"token": token, "enabled": a is not None,
                "model": (db.get("status:capabilities") or {}).get("llm"), **(a.counts() if a else {})}

    @app.get("/api/ai/messages")
    def ai_messages(after: int = 0):
        a = assistant()
        return {"messages": a.messages(after), **a.counts()}

    @app.post("/api/ai/chat")
    async def ai_chat(request: Request):
        a, body = assistant(), await body_of(request)
        text = str(body.get("text") or "").strip()
        if not text:
            raise HTTPException(400, "Say something first.")
        if a.busy:
            raise HTTPException(409, "Flect is still answering.")
        return stream(a.chat(text, local(body)))

    @app.post("/api/ai/brief")
    async def ai_brief(request: Request):
        a, body = assistant(), await body_of(request)
        if a.busy:
            raise HTTPException(409, "Flect is still answering.")
        return stream(a.brief(local(body), force=bool(body.get("force"))))

    @app.post("/api/ai/actions/{action_id}/approve")
    async def ai_approve(action_id: int):
        try:
            return await assistant().approve(action_id)
        except LookupError:
            raise HTTPException(404, "No such suggestion.") from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/ai/actions/{action_id}/dismiss")
    def ai_dismiss(action_id: int):
        try:
            return assistant().dismiss(action_id)
        except LookupError:
            raise HTTPException(404, "No such suggestion.") from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    return app
