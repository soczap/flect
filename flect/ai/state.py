"""What Flect AI knows: a compact, redacted snapshot of Flect's state, plus read-only lookups the model can ask for.

Everything here is read from the database and the daemon's live buffers. Strings that came from logs, tracebacks,
pull requests or scanners are attacker-influenced; the system prompt tells the model to treat them as evidence.
"""
from __future__ import annotations

import hashlib
import json
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flect.config import CAPABILITIES
from flect.db import canonical, now
from flect.redact import redact, redact_obj

QUIET_DECISIONS = "decision NOT LIKE 'status:%' AND decision NOT IN ('comment_pr','label_pr')"


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat(timespec="seconds")


def _cut(value, n: int = 240):
    if isinstance(value, str) and len(value) > n:
        return value[:n] + "…"
    return value


def _compact_details(raw: str | None) -> dict:
    """The incident fields that explain it, without tracebacks or bulky evidence."""
    d = json.loads(raw or "{}")
    keep = ("reason", "classification", "exception", "signature", "crashed_sha", "ip", "rule", "name", "kind",
            "location", "days_left", "expires", "details", "severity")
    return {k: _cut(d[k]) for k in keep if d.get(k) not in (None, "", [])}


def fingerprint(db) -> str:
    """Changes whenever something an operator would want to hear about changes."""
    parts = [
        db.one("SELECT MAX(id) m FROM incidents")["m"],
        db.all("SELECT id, state FROM incidents WHERE state!='resolved' ORDER BY id"),
        db.one(f"SELECT MAX(id) m FROM actions WHERE {QUIET_DECISIONS}")["m"],
        db.one("SELECT MAX(id) m FROM deployments")["m"],
        db.one("SELECT COUNT(*) n FROM blocks WHERE active=1")["n"],
        bool((db.get("health:prod") or {}).get("http_ok")),
        db.get("writes_paused"),
    ]
    return hashlib.sha256(canonical(parts).encode()).hexdigest()[:16]


def snapshot(live, since: str | None = None) -> dict:
    db, cfg = live.db, live.cfg
    engine = getattr(live, "engine", None)
    modes = {c: (engine.mode(c) if engine else db.get(f"mode:{c}") or cfg.mode(c)) for c in CAPABILITIES}
    h = db.get("health:prod") or {}
    hist = list(getattr(live, "health_hist", []) or [])
    ok_pts = [p for p in hist if p[1]]
    caps = db.get("status:capabilities") or {}
    dos = db.get("dos:snapshot") or {}
    t = cfg["target"]
    state = {
        "now_utc": now(),
        "target": {"name": t["name"].upper(), "unit": t["prod_unit"], "prod_url": t["prod_url"],
                   "repo": cfg["github"]["repo"], "prod_branch": cfg["github"]["prod_branch"],
                   "uat_branch": cfg["github"]["feature_base"]},
        "production": {
            "healthy": bool(h.get("http_ok")), "http_status": h.get("http_status"), "error": h.get("error"),
            "latency_ms": round(h["latency_ms"]) if h.get("latency_ms") else None,
            "unit_state": h.get("active_state"), "systemd_restarts": h.get("n_restarts"),
            "uptime_s": h.get("uptime_s"),
            "availability_last_hour_pct": round(100 * len(ok_pts) / len(hist), 2) if hist else None,
            "failed_checks_last_hour": len(hist) - len(ok_pts),
        },
        "guards": modes,
        "github_writes_paused": db.get("writes_paused"),
        "dependencies": {k: caps.get(k) for k in ("sandbox", "nft", "uat", "llm", "github_poll")},
        "traffic": {"requests_per_s": dos.get("global_rps"), "baseline_rps": dos.get("baseline_rps"),
                    "flooding": dos.get("flooding"), "top_talkers_60s": (dos.get("top_talkers_60s") or [])[:5]},
        "open_incidents": [
            {"id": r["id"], "kind": r["kind"], "severity": r["severity"], "state": r["state"],
             "opened": r["opened_ts"], "title": r["title"], "flect_summary": _cut(r["summary"], 300),
             "github_issue": r["github_issue"], "facts": _compact_details(r["details"])}
            for r in db.all("SELECT * FROM incidents WHERE state!='resolved' ORDER BY id DESC LIMIT 12")],
        "recently_resolved": [
            {"id": r["id"], "kind": r["kind"], "severity": r["severity"], "opened": r["opened_ts"],
             "closed": r["closed_ts"], "title": r["title"], "how": _cut(r["summary"], 200)}
            for r in db.all("SELECT * FROM incidents WHERE state='resolved' AND COALESCE(closed_ts, opened_ts) > ? "
                            "ORDER BY id DESC LIMIT 8", (_iso(72),))],
        "recent_actions": [
            {"ts": r["ts"], "did": r["decision"], "target": r["target"], "mode": r["mode"],
             "ok": None if r["ok"] is None else bool(r["ok"]), "result": _cut(r["result"], 160),
             "incident": r["incident_id"]}
            for r in db.all(f"SELECT * FROM actions WHERE {QUIET_DECISIONS} ORDER BY id DESC LIMIT 15")],
        "active_blocks": [
            {"ip": r["ip"], "rule": r["rule_id"], "ttl": r["ttl"], "expires": r["expires_ts"], "reason": _cut(r["reason"], 120)}
            for r in db.all("SELECT * FROM blocks WHERE active=1 AND expires_ts > ? ORDER BY id DESC LIMIT 10", (now(),))],
        "keys_needing_attention": [
            {"name": r["name"], "kind": r["kind"], "level": r["alert_level"], "days_left": r["days_left"],
             "details": _cut(r["details"], 160)}
            for r in db.all("SELECT * FROM keys WHERE alert_level IS NOT NULL AND alert_level!='ok' ORDER BY name")],
        "keys_ok": (db.one("SELECT COUNT(*) n FROM keys WHERE alert_level='ok'") or {}).get("n", 0),
        "deployments": [
            {"env": r["env"], "sha": r["sha"][:12], "trigger": r["trigger"], "state": r["state"], "at": r["started_ts"],
             "notes": _cut(r["notes"], 120)}
            for r in db.all("SELECT * FROM deployments ORDER BY id DESC LIMIT 5")],
        "last_known_good": (db.one("SELECT sha FROM deployments WHERE env='prod' AND state='lkg' ORDER BY id DESC LIMIT 1")
                            or {}).get("sha", "")[:12] or None,
        "pull_requests": [
            {"number": r["number"], "kind": r["kind"], "base": r["base"], "state": r["state"], "risk": r["risk"],
             "title": _cut(r["title"], 120), "updated": r["updated_ts"]}
            for r in db.all("SELECT * FROM prs ORDER BY updated_ts DESC LIMIT 8")],
        "log_anomalies_24h": [
            {"ts": r["ts"], "kind": r["kind"], "severity": r["severity"],
             "detail": _cut(json.loads(r["payload"] or "{}").get("detail"), 160)}
            for r in db.all("SELECT * FROM signals WHERE source='logs' AND ts > ? ORDER BY id DESC LIMIT 8", (_iso(24),))],
        "reports": [
            {"id": r["id"], "kind": r["kind"], "pr": r["pr_number"], "max_severity": r["max_severity"], "at": r["created_ts"]}
            for r in db.all("SELECT * FROM reports ORDER BY id DESC LIMIT 6")],
    }
    if since:
        state["since_operator_last_here"] = {
            "since": since,
            "incidents_opened": [f"#{r['id']} {r['title']} ({r['state']})" for r in
                                 db.all("SELECT id, title, state FROM incidents WHERE opened_ts > ? ORDER BY id", (since,))][:12],
            "incidents_resolved": [f"#{r['id']} {r['title']}: {_cut(r['summary'] or 'resolved', 140)}" for r in
                                   db.all("SELECT id, title, summary FROM incidents WHERE state='resolved' AND closed_ts > ? "
                                          "ORDER BY id", (since,))][:12],
            "actions": (db.one(f"SELECT COUNT(*) n FROM actions WHERE ts > ? AND {QUIET_DECISIONS}", (since,)) or {}).get("n", 0),
            "ips_blocked": [r["ip"] for r in db.all("SELECT DISTINCT ip FROM blocks WHERE created_ts > ?", (since,))][:10],
            "deployments": [f"{r['env']} {r['sha'][:7]} ({r['trigger']}, {r['state']})" for r in
                            db.all("SELECT * FROM deployments WHERE started_ts > ? ORDER BY id", (since,))][:8],
        }
    return redact_obj(state)


# ── lookups: extra detail the model may request mid-answer ─────────────────
LOOKUP_KINDS = ("incident", "report", "logs", "pr")


def _tail(path: str, lines: int) -> list[str]:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 256_000))
            data = fh.read().decode("utf-8", "replace")
    except OSError:
        return []
    return list(deque(data.splitlines(), maxlen=lines))


def lookup(live, kind: str, ref: str) -> dict:
    db, cfg = live.db, live.cfg
    ref = str(ref or "").strip().lstrip("#")
    if kind == "incident":
        row = db.one("SELECT * FROM incidents WHERE id=?", (int(ref),)) if ref.isdigit() else None
        if not row:
            return {"error": f"no incident {ref}"}
        details = json.loads(row.pop("details") or "{}")
        if isinstance(details.get("traceback"), str):
            details["traceback"] = details["traceback"][-2500:]
        row.pop("dedupe_key", None)
        row["details"] = details
        row["actions"] = db.all("SELECT ts, decision, target, mode, ok, result FROM actions WHERE incident_id=? "
                                "ORDER BY id DESC LIMIT 15", (row["id"],))
        return redact_obj(row)
    if kind == "report":
        row = db.one("SELECT * FROM reports WHERE id=?", (int(ref),)) if ref.isdigit() else None
        if not row:
            return {"error": f"no report {ref}"}
        path = Path(row["path"]).resolve()
        if not path.is_relative_to((cfg.data_dir / "reports").resolve()):
            return {"error": "report outside the report store"}
        try:
            text = path.read_text()
        except OSError:
            return {"error": "report file missing"}
        return {"id": row["id"], "kind": row["kind"], "pr": row["pr_number"], "text": redact(text[:6000])}
    if kind == "logs":
        out = {}
        for p in cfg["target"]["logs"]:
            lines = _tail(p, 400)
            errors = [ln for ln in lines if any(m in ln for m in ("ERROR", "CRITICAL", "Traceback", "Exception"))]
            out[Path(p).name] = {"last_lines": [_cut(ln, 300) for ln in lines[-25:]],
                                 "recent_errors": [_cut(ln, 300) for ln in errors[-20:]]}
        return redact_obj(out)
    if kind == "pr":
        row = db.one("SELECT * FROM prs WHERE number=? ORDER BY updated_ts DESC LIMIT 1", (int(ref),)) if ref.isdigit() else None
        if not row:
            return {"error": f"Flect has not reviewed PR {ref}"}
        row["statuses"] = json.loads(row["statuses"] or "{}")
        row["llm_verdict"] = json.loads(row["llm_verdict"]) if row.get("llm_verdict") else None
        row["findings"] = db.all("SELECT rule_id, severity, title, file, line FROM findings WHERE scope='pr' AND ref=? "
                                 "ORDER BY created_ts DESC LIMIT 20", (str(row["number"]),))
        return redact_obj(row)
    return {"error": f"unknown lookup {kind}"}
