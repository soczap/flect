"""Actions an operator approved in the Flect AI console (flect/ai).

The model only proposes these. flect/ai/actions.py validates each proposal, the operator approves it, and it runs
here through `act(..., by=)`: it executes whatever the capability's mode and lands in the audit chain with who
approved it.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone

from flect.db import now
from flect.policy import rules


class OperatorActions:
    async def operator_restart_prod(self, by: str):
        """Restart production and wait for it to answer health checks. Crash detection holds off meanwhile."""
        async with self.deploy_lock["prod"]:
            sha = await asyncio.to_thread(self.prod.current_sha)
            self.deploying_until = time.time() + 600
            try:
                return await self.act("crash", "restart_prod", self.prod.unit, {"sha": sha[:12]},
                                      lambda: asyncio.to_thread(self.prod.restart), by=by)
            finally:
                self.deploying_until = time.time() + 15

    async def operator_rollback(self, by: str):
        """Deploy the last-known-good commit. Returns (sha, DeployResult | None)."""
        lkg = rules.last_known_good(self.db)
        if not lkg:
            raise ValueError("there is no last-known-good commit yet")
        return lkg["sha"], await self.deploy_prod(lkg["sha"], "operator_rollback", "crash", by=by)

    async def operator_recheck(self, by: str) -> list:
        """Run every key, certificate and dependent-service check now; incidents whose checks pass resolve."""
        from flect.sources import keys as keys_src
        results = await asyncio.to_thread(keys_src.run_all, self.cfg)
        await self.on_key_results(results)
        failing = [r.name for r in results if r.probe_ok is False]
        self.db.record_action("recheck_services", "keys", {"checked": len(results), "approved_by": by}, "operator",
                              True, f"failing: {', '.join(failing)}" if failing else "all checks pass")
        return results

    async def operator_block(self, ip: str, ttl: str, by: str) -> bool:
        offence = rules.offence_count(self.db, ip) + 1
        expires = datetime.now(timezone.utc) + rules.ttl_delta(ttl)
        reason = "blocked by the operator"
        ok = await self.act("dos", "block_ip", ip, {"ttl": ttl, "rule": "OPERATOR", "reason": reason},
                            (lambda: self.nft.block(ip, ttl)) if self.nft else None, by=by)
        self.db.execute("INSERT INTO blocks(ip,rule_id,reason,offence,ttl,created_ts,expires_ts,active,mode,incident_id) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (ip, "OPERATOR", reason, offence, ttl, now(), expires.isoformat(timespec="seconds"),
                         1 if ok else 0, "enforce" if ok else "observe", None))
        return bool(ok)

    async def operator_unblock(self, ip: str, by: str) -> bool:
        applied = self.db.one("SELECT id FROM blocks WHERE ip=? AND active=1 AND mode='enforce'", (ip,))
        if applied and self.nft:
            ok = bool(await self.act("dos", "unblock_ip", ip, {}, lambda: self.nft.unblock(ip), by=by))
        else:
            ok = True
            self.db.record_action("unblock_ip", ip, {"approved_by": by}, "operator", True, "no firewall rule to remove")
        if ok:
            self.db.execute("UPDATE blocks SET active=0, unblocked_by=? WHERE ip=? AND active=1", (by, ip))
        return ok

    def operator_resolve(self, incident_id: int, note: str, by: str) -> None:
        self.resolve_incident(incident_id, note)
        self.db.record_action("resolve_incident", f"incident #{incident_id}", {"note": note, "approved_by": by},
                              "operator", True, "resolved", incident_id)

    def operator_set_mode(self, capability: str, mode: str, by: str) -> None:
        before = self.mode(capability)
        self.db.set(f"mode:{capability}", mode)
        self.db.record_action("set_mode", capability, {"mode": mode, "was": before, "approved_by": by}, "operator",
                              True, "ok")

    def operator_pause(self, reason: str, by: str) -> None:
        self.set_paused(reason)
        self.db.record_action("pause_github_writes", "github", {"reason": reason, "approved_by": by}, "operator",
                              True, "paused")

    def operator_resume(self, by: str) -> None:
        was = self.writes_paused()
        self.set_paused(None)
        self.db.record_action("resume_github_writes", "github", {"was": was, "approved_by": by}, "operator",
                              True, "resumed")

    async def operator_retry_fix(self, incident_id: int, by: str) -> dict | None:
        """Run fix-forward again for a code crash, skipping the 6-hour already-attempted check."""
        from flect.detect.crash import parse_traceback
        row = self.db.one("SELECT details FROM incidents WHERE id=?", (incident_id,))
        details = json.loads((row or {}).get("details") or "{}")
        tb = parse_traceback(details.get("traceback") or "", self.prod.repo_dir)
        if not tb or not tb.app_frames:
            raise ValueError("the incident has no application traceback to fix")
        sha = details.get("crashed_sha") or await asyncio.to_thread(self.prod.current_sha)
        self.db.record_action("retry_fix", f"incident #{incident_id}", {"signature": tb.signature, "approved_by": by},
                              "operator", None, "started", incident_id)
        await self._fix_forward_safe(incident_id, tb, sha, force=True)
        return self.db.one("SELECT state, summary FROM incidents WHERE id=?", (incident_id,))
