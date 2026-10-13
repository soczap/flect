"""Flect daemon: wires sources → detectors → policy engine → actuators, plus dashboard and control socket."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from flect import config as config_mod
from flect.actuators.deploy import Deployer
from flect.actuators.git import Git, GitHub
from flect.actuators.nft import Nft
from flect.actuators.notify import Notifier
from flect.actuators.sandbox import Sandbox
from flect.db import DB, now
from flect.detect.anomaly import AnomalyDetector
from flect.detect.crash import CrashDetector, parse_traceback
from flect.detect.dos import DosDetector
from flect.gateway.llm import P_NARRATIVE, Gateway, build_messages
from flect.policy.engine import Engine
from flect.sources import health as health_src
from flect.sources import keys as keys_src
from flect.sources.github import GitHubPoller
from flect.sources.logs import LogTailer

log = logging.getLogger("flect")

NARRATIVE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["summary", "likely_cause", "recommended_followups"],
    "properties": {"summary": {"type": "string", "maxLength": 1200}, "likely_cause": {"type": "string", "maxLength": 600},
                   "recommended_followups": {"type": "array", "items": {"type": "string", "maxLength": 200}, "maxItems": 5}},
}


class Flect:
    def __init__(self, cfg):
        self.cfg = cfg
        data = cfg.data_dir
        data.mkdir(parents=True, exist_ok=True)
        (data / "work").mkdir(exist_ok=True)
        os.environ.setdefault("SOC_BANDIT", str(Path("~/deepseek/security/.scanner-venv/bin/bandit").expanduser()))
        self.db = DB(data / "flect.db")
        t, gh = cfg["target"], cfg["github"]
        self.gateway = Gateway(cfg, self.db)
        self.github = GitHub(gh["repo"])
        self.nft = Nft(cfg["nft"]["helper"])
        self.sandbox = Sandbox(cfg["sandbox"])
        repo_url = f"https://github.com/{gh['repo']}.git"
        self.prod = Deployer(t["prod_dir"], t["prod_unit"], t["prod_url"], t["health_path"], t["venv"], repo_url)
        self.uat = (Deployer(t["uat_dir"], t["uat_unit"], t["uat_url"], t["health_path"], None, repo_url)
                    if Path(t["uat_dir"]).is_dir() else None)
        notify_github = bool(cfg.data.get("notify", {}).get("github", False))
        self.notifier = Notifier(self.db, data / "reports", self.github, notify_github)
        self.clone = Git(str(data / "work" / "clone"), gh["identity_name"], gh["identity_email"])
        venv = t["venv"]
        self.engine = Engine(
            cfg, self.db, gateway=self.gateway, github=self.github, nft=self.nft, prod=self.prod, uat=self.uat,
            sandbox=self.sandbox, notifier=self.notifier, clone=self.clone,
            paths={"mirror": str(data / "work" / "mirror.git"), "work": str(data / "work")},
            test_argv=[f"{venv}/bin/python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x"],
            sandbox_ro=[venv])
        self.dos = DosDetector(cfg["dos"])
        self.crash = CrashDetector(cfg["crash"], t["prod_dir"])
        self.anomaly = AnomalyDetector()
        self.tailer = LogTailer(self.db, t["logs"])
        self.tailer.subscribe(self._on_record)
        self.poller = GitHubPoller(self.db, gh["repo"], gh["poll_interval_s"], self.engine.on_pr, self.engine.on_branch_move)
        self.pending: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.started = time.time()
        self.tasks: list[asyncio.Task] = []

    # ── log records (called from the tailer thread) ────────────────────────
    @staticmethod
    def _event_time(rec) -> float:
        """Prefer the log line's own timestamp (robust to batched reads); fall back to arrival time."""
        now_t = time.time()
        if rec.ts:
            try:
                from datetime import datetime
                t = datetime.fromisoformat(str(rec.ts).replace("Z", "+00:00")).timestamp()
                if abs(now_t - t) < 300:
                    return t
            except ValueError:
                pass
        return now_t

    def _on_record(self, rec) -> None:
        t = self._event_time(rec)
        if rec.kind == "access" and rec.ip:
            self.dos.observe(rec.ip, rec.path or "", rec.method or "", rec.status or 0, t)
            for a in self.anomaly.observe_access(rec.status or 0, t):
                self._enqueue(("anomaly", a))
            return
        text = rec.exc if rec.exc else (rec.msg if rec.kind == "raw" else None)
        if text and ("Traceback" in text or 'File "' in text):
            ev = self.crash.observe_traceback(text, t)
            tb = self.crash.last_tb
            for a in self.anomaly.observe_error(t, tb.signature if tb else None, tb.exc_type if tb else None):
                self._enqueue(("anomaly", a))
            if ev:
                self._enqueue(("crash", ev))
        elif rec.level in ("ERROR", "CRITICAL"):
            for a in self.anomaly.observe_error(t):
                self._enqueue(("anomaly", a))

    def _enqueue(self, item) -> None:
        try:
            self.pending.put_nowait(item)
        except asyncio.QueueFull:
            log.warning("event queue full; dropping %s", item[0])

    # ── loops ──────────────────────────────────────────────────────────────
    async def _events(self) -> None:
        while True:
            kind, payload = await self.pending.get()
            try:
                if kind == "crash":
                    await self.engine.on_crash(payload)
                elif kind == "anomaly":
                    await self._on_anomaly(payload)
            except Exception:  # noqa: BLE001
                log.exception("handling %s failed", kind)

    async def _on_anomaly(self, a) -> None:
        self.db.signal("logs", a.kind, a.severity, None, {"detail": a.detail, **a.evidence},
                       dedupe_key=f"{a.kind}:{a.evidence.get('signature') or a.evidence.get('minute')}")
        if a.severity == "high":
            incident_id, created = self.db.open_incident("anomaly", a.severity, f"Log anomaly: {a.detail}",
                                                         a.evidence, dedupe_key=f"anomaly:{a.kind}")
            if created:
                self.notifier.incident(incident_id, f"Log anomaly: {a.kind}", a.detail, ["anomaly"])

    async def _dos_tick(self) -> None:
        while True:
            await asyncio.sleep(1)
            for req in self.dos.tick(time.time()):
                await self.engine.on_block_request(req)
                asyncio.create_task(self._narrate_dos(req))
            await self.engine.on_flood_change(self.dos.flooding)
            self.db.set("dos:snapshot", self.dos.snapshot())

    async def _narrate_dos(self, req) -> None:
        msgs = build_messages("dos_narrative", [{"id": req.rule_id, "reason": req.reason}],
                              {"ip": req.ip, "snapshot": self.dos.snapshot()}, {},
                              "Explain this traffic incident for an operator in plain words.", 18000)
        try:
            out = await self.gateway.ask("dos_narrative", P_NARRATIVE, msgs, NARRATIVE_SCHEMA, ref=req.ip)
            row = self.db.one("SELECT id FROM incidents WHERE dedupe_key=?", (f"dos:{req.ip}",))
            if row:
                self.db.update_incident(row["id"], llm_summary=json.dumps(out))
        except Exception:  # noqa: BLE001 — narrative is optional
            pass

    async def _health(self) -> None:
        t = self.cfg["target"]
        while True:
            p = await asyncio.to_thread(health_src.probe, t["prod_url"], t["health_path"], t["prod_unit"])
            self.db.set("health:prod", p.__dict__)
            ev = self.crash.observe_probe(p, time.time())
            if ev:
                await self.engine.on_crash(ev)
            if p.http_ok:
                for row in self.db.all("SELECT id FROM incidents WHERE kind='crash' AND dedupe_key='crash:down' "
                                       "AND state IN ('mitigated','open','mitigating')"):
                    if time.time() > self.engine.deploying_until:
                        self.db.update_incident(row["id"], state="resolved")
            await asyncio.to_thread(self.engine.track_prod_version, p.http_ok)
            await asyncio.sleep(self.cfg["crash"]["health_interval_s"])

    async def _keys(self) -> None:
        while True:
            try:
                results = await asyncio.to_thread(keys_src.run_all, self.cfg)
                await self.engine.on_key_results(results)
            except Exception:  # noqa: BLE001
                log.exception("key checks failed")
            await asyncio.sleep(self.cfg["keys"]["interval_s"])

    async def _housekeeping(self) -> None:
        while True:
            self.engine.expire_blocks()
            self.db.set("status:capabilities", {
                "sandbox": (await asyncio.to_thread(self.sandbox.available))[1],
                "nft": "ok" if await asyncio.to_thread(self.nft.available) else "helper not installed",
                "uat": "configured" if self.uat else "not configured",
                "llm": "ok" if await asyncio.to_thread(self.gateway.client.health) else "unavailable",
                "github_poll": self.poller.last_error or "ok",
                "log_lines": self.tailer.lines_seen,
                "llm_queue": self.gateway.stats(),
                "updated": now(),
            })
            await asyncio.sleep(30)

    # ── control socket ─────────────────────────────────────────────────────
    async def _control(self, reader, writer) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), 10)
            req = json.loads(line or b"{}")
            resp = await self.handle_command(req)
        except Exception as exc:  # noqa: BLE001
            resp = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        writer.write((json.dumps(resp, default=str) + "\n").encode())
        await writer.drain()
        writer.close()

    async def handle_command(self, req: dict) -> dict:
        from flect.config import CAPABILITIES, MODES
        cmd = req.get("cmd")
        if cmd == "status":
            return {"ok": True, "uptime_s": round(time.time() - self.started),
                    "modes": {c: self.engine.mode(c) for c in CAPABILITIES},
                    "writes_paused": self.engine.writes_paused(),
                    "capabilities": self.db.get("status:capabilities"), "health": self.db.get("health:prod"),
                    "dos": self.db.get("dos:snapshot")}
        if cmd == "unblock":
            return {"ok": await self.engine.unblock(req["ip"], "cli")}
        if cmd == "mode":
            cap, mode = req["capability"], req["mode"]
            if cap not in CAPABILITIES or mode not in MODES:
                return {"ok": False, "error": f"capability in {CAPABILITIES}, mode in {MODES}"}
            self.db.set(f"mode:{cap}", mode)
            self.db.record_action("set_mode", cap, {"mode": mode}, "enforce", True, "cli")
            return {"ok": True}
        if cmd == "pause":
            self.engine.set_paused(req.get("reason") or "paused by operator")
            return {"ok": True}
        if cmd == "resume":
            self.engine.set_paused(None)
            return {"ok": True}
        return {"ok": False, "error": f"unknown command {cmd!r}"}

    # ── run ────────────────────────────────────────────────────────────────
    async def run(self) -> None:
        from flect.server import build_app
        import uvicorn
        self.gateway.start()
        await self.engine.restore_blocks()
        sock = self.cfg.data_dir / "flect.sock"
        if sock.exists():
            sock.unlink()
        server = await asyncio.start_unix_server(self._control, path=str(sock))
        os.chmod(sock, 0o600)
        dash = self.cfg["dashboard"]
        uv = uvicorn.Server(uvicorn.Config(build_app(self.db, self.cfg, self.engine), host=dash["host"],
                                           port=int(dash["port"]), log_level="warning", access_log=False))
        loops = {"logs": self.tailer.run, "dos": self._dos_tick, "health": self._health, "keys": self._keys,
                 "github": self.poller.run, "events": self._events, "housekeeping": self._housekeeping,
                 "dashboard": uv.serve}
        self.tasks = [asyncio.create_task(self._supervise(name, factory), name=name) for name, factory in loops.items()]
        log.info("Flect running: modes=%s dashboard=http://%s:%s", self.cfg["modes"], dash["host"], dash["port"])
        async with server:
            await asyncio.gather(*self.tasks)

    async def _supervise(self, name: str, factory) -> None:
        """Restart a crashed loop with exponential backoff instead of taking the whole daemon down."""
        backoff = 1.0
        while True:
            started = time.monotonic()
            try:
                await factory()
                return
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("loop %s crashed; restarting in %.0fs", name, backoff)
                self.db.signal("flect", "loop_crashed", "high", name, {"loop": name}, dedupe_key=None)
            if time.monotonic() - started > 300:
                backoff = 1.0
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 120)


def main(config_path: str | None = None) -> None:
    logging.basicConfig(level=os.environ.get("FLECT_LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = config_mod.load(config_path)
    asyncio.run(Flect(cfg).run())
