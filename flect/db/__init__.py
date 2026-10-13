"""SQLite state store (WAL). Small synchronous calls guarded by a lock; safe from asyncio tasks."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from flect.redact import redact_obj

SCHEMA = Path(__file__).with_name("schema.sql")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


class DB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA busy_timeout=5000")
            self.conn.executescript(SCHEMA.read_text())

    # ── generic ────────────────────────────────────────────────────────────
    def execute(self, sql: str, params=()) -> sqlite3.Cursor:
        with self.lock:
            return self.conn.execute(sql, params)

    def all(self, sql: str, params=()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params=()) -> dict | None:
        with self.lock:
            row = self.conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    # ── kv ─────────────────────────────────────────────────────────────────
    def get(self, key: str, default=None):
        row = self.one("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def set(self, key: str, value) -> None:
        self.execute("INSERT INTO kv(key,value,updated_ts) VALUES(?,?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_ts=excluded.updated_ts",
                     (key, json.dumps(value, default=str), now()))

    # ── signals / incidents ────────────────────────────────────────────────
    def signal(self, source: str, kind: str, severity: str, subject: str | None, payload: dict,
               dedupe_key: str | None = None) -> int | None:
        cur = self.execute(
            "INSERT OR IGNORE INTO signals(ts,source,kind,severity,subject,payload,dedupe_key) VALUES(?,?,?,?,?,?,?)",
            (now(), source, kind, severity, subject, canonical(redact_obj(payload)), dedupe_key))
        return cur.lastrowid if cur.rowcount else None

    def open_incident(self, kind: str, severity: str, title: str, details: dict,
                      dedupe_key: str | None = None) -> tuple[int, bool]:
        """Return (incident_id, created). An open incident with the same dedupe key is reused."""
        if dedupe_key:
            row = self.one("SELECT id FROM incidents WHERE dedupe_key=? AND state NOT IN ('resolved')", (dedupe_key,))
            if row:
                return row["id"], False
            # A resolved incident may hold the key; release it so a new one can open.
            self.execute("UPDATE incidents SET dedupe_key=NULL WHERE dedupe_key=?", (dedupe_key,))
        cur = self.execute(
            "INSERT INTO incidents(kind,severity,state,opened_ts,title,details,dedupe_key) VALUES(?,?,?,?,?,?,?)",
            (kind, severity, "open", now(), title, canonical(redact_obj(details)), dedupe_key))
        return cur.lastrowid, True

    def update_incident(self, incident_id: int, **fields) -> None:
        if "details" in fields:
            fields["details"] = canonical(redact_obj(fields["details"]))
        if fields.get("state") == "resolved":
            fields.setdefault("closed_ts", now())
        cols = ", ".join(f"{k}=?" for k in fields)
        self.execute(f"UPDATE incidents SET {cols} WHERE id=?", (*fields.values(), incident_id))

    # ── audit log (hash chained) ───────────────────────────────────────────
    def record_action(self, decision: str, target: str, params: dict, mode: str,
                      ok: bool | None, result: str | None, incident_id: int | None = None) -> int:
        with self.lock:
            prev = self.conn.execute("SELECT hash FROM actions ORDER BY id DESC LIMIT 1").fetchone()
            prev_hash = prev["hash"] if prev else "0" * 64
            ts = now()
            body = canonical({"ts": ts, "decision": decision, "target": target, "params": redact_obj(params),
                              "mode": mode, "ok": ok, "result": result, "incident_id": incident_id})
            digest = hashlib.sha256((prev_hash + body).encode()).hexdigest()
            cur = self.conn.execute(
                "INSERT INTO actions(ts,decision,target,params,mode,ok,result,incident_id,prev_hash,hash) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (ts, decision, target, canonical(redact_obj(params)), mode,
                 None if ok is None else int(ok), result, incident_id, prev_hash, digest))
            return cur.lastrowid

    def verify_audit_chain(self) -> bool:
        prev_hash = "0" * 64
        for row in self.all("SELECT * FROM actions ORDER BY id"):
            body = canonical({"ts": row["ts"], "decision": row["decision"], "target": row["target"],
                              "params": json.loads(row["params"]), "mode": row["mode"],
                              "ok": None if row["ok"] is None else bool(row["ok"]),
                              "result": row["result"], "incident_id": row["incident_id"]})
            if row["prev_hash"] != prev_hash:
                return False
            if hashlib.sha256((prev_hash + body).encode()).hexdigest() != row["hash"]:
                return False
            prev_hash = row["hash"]
        return True
