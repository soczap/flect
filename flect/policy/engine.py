"""Policy engine: the ONLY component allowed to call actuators.

Every side effect goes through `act()`, which
  - checks the capability's mode (off / observe / enforce) and the global write pause,
  - executes in enforce mode, or records a `would_do` action in observe mode,
  - writes a hash-chained audit row either way.
Detectors and the LLM only produce facts; the rules below turn facts into decisions.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from flect.db import DB, now
from flect.policy import rules
from flect.policy.cicd import CicdFlows
from flect.policy.crashflow import CrashFlows
from flect.policy.operator import OperatorActions

log = logging.getLogger("flect.policy")


class Engine(CrashFlows, CicdFlows, OperatorActions):
    def __init__(self, cfg, db: DB, *, gateway=None, github=None, nft=None, prod=None, uat=None,
                 sandbox=None, notifier=None, clone=None, paths: dict | None = None,
                 test_argv: list[str] | None = None, sandbox_ro: list[str] | None = None):
        self.cfg = cfg
        self.db = db
        self.gateway = gateway
        self.github = github
        self.nft = nft
        self.prod = prod          # Deployer for prod
        self.uat = uat            # Deployer for UAT
        self.sandbox = sandbox
        self.notifier = notifier
        self.clone = clone        # Git working clone of the target repo (for hotfix branches)
        self.paths = paths or {}  # mirror, work
        self.test_argv = test_argv or []
        self.sandbox_ro = sandbox_ro or []
        self.deploy_lock = {"prod": asyncio.Lock(), "uat": asyncio.Lock()}
        self.deploying_until = 0.0     # crash detection is suppressed while Flect itself restarts prod
        self.flood_on = False

    # ── modes / pause ──────────────────────────────────────────────────────
    def mode(self, capability: str) -> str:
        override = self.db.get(f"mode:{capability}")
        return override or self.cfg.mode(capability)

    def writes_paused(self) -> str | None:
        return self.db.get("writes_paused")

    def set_paused(self, reason: str | None) -> None:
        self.db.set("writes_paused", reason)

    async def act(self, capability: str, decision: str, target: str, params: dict, fn=None,
                  incident_id: int | None = None, github_write: bool = False, by: str | None = None):
        """Execute `fn` (sync or async) only in enforce mode, or when an operator approved it (`by`); always audit.

        Operator-approved actions run whatever the capability's mode (modes govern what Flect does on its own)
        and are audited with mode "operator" and who approved them. The GitHub write pause still applies.
        """
        mode = self.mode(capability)
        if mode == "off" and by is None:
            return None
        if by is not None:
            params = {**params, "approved_by": by}
        paused = self.writes_paused()
        executes = mode == "enforce" or by is not None
        if not executes or fn is None or (github_write and paused):
            why = "observe" if not executes else ("paused: " + paused if paused else "no-op")
            self.db.record_action(decision, target, params, "observe", None, f"would_do ({why})", incident_id)
            return None
        ran_as = "operator" if by is not None else "enforce"
        try:
            result = fn()
            if asyncio.iscoroutine(result):
                result = await result
            self.db.record_action(decision, target, params, ran_as, True, str(result)[:500] if result is not None else "ok",
                                  incident_id)
            return result if result is not None else True
        except Exception as exc:  # noqa: BLE001
            log.exception("action %s on %s failed", decision, target)
            self.db.record_action(decision, target, params, ran_as, False, f"{type(exc).__name__}: {exc}"[:500],
                                  incident_id)
            return None

    def resolve_incident(self, incident_id: int, summary: str) -> None:
        """Resolve locally and, if it was filed on GitHub, comment and close the issue."""
        self.db.update_incident(incident_id, state="resolved", summary=summary)
        if self.notifier:
            self.notifier.resolved(incident_id, summary)

    # ── DoS ────────────────────────────────────────────────────────────────
    async def on_block_request(self, req) -> None:
        offence = rules.offence_count(self.db, req.ip) + 1
        ttl = rules.ttl_for_offence(self.cfg["dos"]["ttl_ladder"], offence)
        incident_id, created = self.db.open_incident(
            "dos", "high", f"Abusive traffic from {req.ip} ({req.rule_id})",
            {"ip": req.ip, "rule": req.rule_id, "reason": req.reason, "evidence": req.evidence},
            dedupe_key=f"dos:{req.ip}")
        expires = datetime.now(timezone.utc) + rules.ttl_delta(ttl)
        mode = self.mode("dos")
        ok = await self.act("dos", "block_ip", req.ip, {"ttl": ttl, "rule": req.rule_id, "reason": req.reason},
                            (lambda: self.nft.block(req.ip, ttl)) if self.nft else None, incident_id)
        self.db.execute("INSERT INTO blocks(ip,rule_id,reason,offence,ttl,created_ts,expires_ts,active,mode,incident_id) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (req.ip, req.rule_id, req.reason, offence, ttl, now(), expires.isoformat(timespec="seconds"),
                         1 if ok else 0, mode if ok else "observe", incident_id))
        if created and self.notifier:
            body = (f"Flect {'blocked' if ok else 'would block (observe mode)'} **{req.ip}** for {ttl}.\n\n"
                    f"- Rule: `{req.rule_id}`\n- Reason: {req.reason}\n- Offence #{offence} in 24h\n"
                    f"- Evidence: `{req.evidence}`\n\nUnblock with `flect unblock {req.ip}`.")
            self.notifier.incident(incident_id, f"DoS: {req.ip} {'blocked' if ok else 'flagged'}", body, ["dos"])

    async def on_flood_change(self, flooding: bool) -> None:
        if flooding == self.flood_on:
            return
        self.flood_on = flooding
        await self.act("dos", "flood_mode_on" if flooding else "flood_mode_off", "nft",
                       {"rate": 50}, (lambda: self.nft.flood(flooding)) if self.nft else None)

    async def unblock(self, ip: str, by: str = "cli") -> bool:
        mode_before = self.mode("dos")
        ok = True
        if self.nft and mode_before == "enforce":
            try:
                self.nft.unblock(ip)
            except Exception as exc:  # noqa: BLE001
                ok = False
                log.warning("unblock %s failed: %s", ip, exc)
        self.db.execute("UPDATE blocks SET active=0, unblocked_by=? WHERE ip=? AND active=1", (by, ip))
        self.db.record_action("unblock_ip", ip, {"by": by}, mode_before, ok, "ok" if ok else "nft error")
        return ok

    def expire_blocks(self) -> None:
        self.db.execute("UPDATE blocks SET active=0 WHERE active=1 AND expires_ts < ?", (now(),))

    async def restore_blocks(self) -> None:
        """nft sets are lost on reboot; re-apply blocks that should still be active."""
        if not self.nft or self.mode("dos") != "enforce":
            return
        for row in self.db.all("SELECT ip, expires_ts FROM blocks WHERE active=1 AND mode='enforce' AND expires_ts > ?", (now(),)):
            remaining = datetime.fromisoformat(row["expires_ts"]) - datetime.now(timezone.utc)
            ttl = rules.ttl_ceiling(remaining)
            try:
                self.nft.block(row["ip"], ttl)
            except Exception as exc:  # noqa: BLE001
                log.warning("restore block %s failed: %s", row["ip"], exc)

    # ── keys / expiry ──────────────────────────────────────────────────────
    async def _token_pause(self, level: str, changed: bool) -> None:
        """Pause GitHub writes while Flect's token is expired or failing; lift that pause once it works again.

        Enforce applies it on every check (so it also takes effect after switching to enforce). Observe records
        the would-do only when the token's level changes, not on every check. An operator's own pause is never
        overwritten or lifted here.
        """
        paused = self.writes_paused() or ""
        by_token = paused.startswith("GitHub token")
        bad = level in ("expired", "failing")
        if not (changed or self.mode("keys") == "enforce"):
            return
        if bad and not paused:
            reason = f"GitHub token {'expired' if level == 'expired' else 'not working'}"
            await self.act("keys", "pause_github_writes", "github", {"reason": reason}, lambda: self.set_paused(reason))
        elif not bad and by_token:
            await self.act("keys", "resume_github_writes", "github", {"was": paused}, lambda: self.set_paused(None))

    async def on_key_results(self, results) -> None:
        if self.mode("keys") == "off":
            return
        warn = self.cfg["keys"]["warn_days"]
        cert_warn = self.cfg["keys"]["cert_warn_days"]
        for st in results:
            days = st.days_left()
            fails = (self.db.get(f"keyfail:{st.name}") or 0) + 1 if st.probe_ok is False else 0
            self.db.set(f"keyfail:{st.name}", fails)
            prev = self.db.one("SELECT alert_level FROM keys WHERE name=?", (st.name,))
            if st.probe_ok is False and fails < 2:
                # One failed probe (e.g. DNS not up yet at boot) is not an outage; Flect re-checks in 2 minutes.
                # Keep the previous level (including "failing"): debounce applies to new outages only.
                level = (prev or {}).get("alert_level") or "ok"
            else:
                level = rules.key_alert_level(st.kind, days, st.probe_ok, warn, cert_warn)
            self.db.execute(
                "INSERT INTO keys(name,kind,location,expires_ts,days_left,last_probe_ts,last_probe_ok,alert_level,details) "
                "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET kind=excluded.kind, location=excluded.location, "
                "expires_ts=excluded.expires_ts, days_left=excluded.days_left, last_probe_ts=excluded.last_probe_ts, "
                "last_probe_ok=excluded.last_probe_ok, alert_level=excluded.alert_level, details=excluded.details",
                (st.name, st.kind, st.location, st.expires.isoformat() if st.expires else None, days, now(),
                 None if st.probe_ok is None else int(st.probe_ok), level, st.details))
            changed = (prev or {}).get("alert_level") != level
            if st.kind == "github_pat":
                await self._token_pause(level, changed)
            if changed and level != "ok":
                sev = "critical" if level in ("expired", "failing") else "high" if level in ("T-1d", "T-3d") else "medium"
                incident_id, created = self.db.open_incident(
                    "expiry", sev, f"{st.name}: {level}",
                    {"name": st.name, "kind": st.kind, "location": st.location, "days_left": days,
                     "expires": st.expires.isoformat() if st.expires else None, "probe_ok": st.probe_ok,
                     "details": st.details}, dedupe_key=f"expiry:{st.name}:{level}")
                if created and self.notifier:
                    when = f"expires {st.expires:%Y-%m-%d %H:%M UTC} ({days} days)" if st.expires else "liveness probe failing"
                    self.notifier.incident(incident_id, f"{st.name} — {level}",
                                           f"**{st.name}** ({st.kind}, `{st.location}`) {when}.\n\n{st.details}\n\n"
                                           + rules.key_runbook(st.kind), ["expiry"])
            elif changed and level == "ok":
                for row in self.db.all("SELECT id FROM incidents WHERE kind='expiry' AND state!='resolved' AND title LIKE ?",
                                       (f"{st.name}:%",)):
                    self.resolve_incident(row["id"], f"{st.name} is healthy again ({st.details or 'probe ok'}).")
