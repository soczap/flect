"""Production crash handling: rollback first (no LLM), then a verified fix-forward hotfix.

This is the only path that may merge into the production branch without a human.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flect.analyze import hotfix, prguard
from flect.db import now
from flect.policy import rules

log = logging.getLogger("flect.crash")


class CrashFlows:
    # ── deployments bookkeeping ────────────────────────────────────────────
    def record_deployment(self, env: str, sha: str, previous: str | None, trigger: str, state: str,
                          notes: str = "") -> int:
        healthy_since = now() if state == "healthy" else None
        return self.db.execute(
            "INSERT INTO deployments(env,sha,previous_sha,trigger,state,started_ts,finished_ts,healthy_since,notes) "
            "VALUES(?,?,?,?,?,?,?,?,?)", (env, sha, previous, trigger, state, now(), now(), healthy_since, notes[:500])).lastrowid

    def track_prod_version(self, healthy: bool) -> None:
        """Bootstrap / notice out-of-band deploys, and promote healthy deployments to last-known-good."""
        try:
            sha = self.prod.current_sha()
        except Exception:  # noqa: BLE001
            return
        latest = self.db.one("SELECT * FROM deployments WHERE env='prod' ORDER BY id DESC LIMIT 1")
        if latest is None or latest["sha"] != sha:
            if healthy:
                self.record_deployment("prod", sha, latest["sha"] if latest else None,
                                       "bootstrap" if latest is None else "manual", "healthy",
                                       "first observation" if latest is None else "changed outside Flect")
            return
        if latest["state"] == "healthy" and healthy and latest["healthy_since"]:
            since = datetime.fromisoformat(latest["healthy_since"])
            open_crash = self.db.one("SELECT id FROM incidents WHERE kind='crash' AND state NOT IN ('resolved')")
            if not open_crash and datetime.now(timezone.utc) - since >= timedelta(minutes=self.cfg["crash"]["lkg_healthy_minutes"]):
                self.db.execute("UPDATE deployments SET state='lkg' WHERE id=?", (latest["id"],))
                log.info("prod %s promoted to last-known-good", sha[:12])
        elif latest["state"] in ("healthy", "lkg") and not healthy:
            self.db.execute("UPDATE deployments SET healthy_since=NULL WHERE id=? AND state='healthy'", (latest["id"],))
        elif latest["state"] == "healthy" and healthy and not latest["healthy_since"]:
            self.db.execute("UPDATE deployments SET healthy_since=? WHERE id=?", (now(), latest["id"]))

    async def deploy_prod(self, sha: str, trigger: str, capability: str, incident_id: int | None = None):
        async with self.deploy_lock["prod"]:
            previous = await asyncio.to_thread(self.prod.current_sha)
            if previous == sha and trigger != "restart":
                return None
            self.deploying_until = time.time() + 600
            try:
                result = await self.act(capability, f"deploy_prod:{trigger}", sha[:12], {"from": previous[:12], "to": sha[:12]},
                                        lambda: asyncio.to_thread(self.prod.deploy, sha), incident_id)
            finally:
                self.deploying_until = time.time() + 15
            if result is None:
                return None
            state = "healthy" if result.ok else "failed"
            self.record_deployment("prod", sha, previous, trigger, state, result.detail)
        # Roll back outside the lock (asyncio.Lock is not re-entrant).
        if not result.ok and trigger not in ("rollback",):
            lkg = rules.last_known_good(self.db)
            if lkg and lkg["sha"] != sha:
                log.warning("deploy of %s failed (%s); rolling back to %s", sha[:12], result.detail, lkg["sha"][:12])
                await self.deploy_prod(lkg["sha"], "rollback", capability, incident_id)
        return result

    # ── crash entry point ──────────────────────────────────────────────────
    async def on_crash(self, event) -> None:
        if time.time() < self.deploying_until:
            log.info("ignoring crash signal during a Flect-initiated deploy: %s", event.reason)
            return
        tb = event.traceback
        key = "crash:down" if event.severity == "S1" else f"crash:{tb.signature if tb else 'unknown'}"
        crashed_sha = await asyncio.to_thread(self.prod.current_sha)
        title = (f"Production down: {event.reason}" if event.severity == "S1"
                 else f"Production error burst: {tb.exc_type if tb else 'error'}")
        incident_id, created = self.db.open_incident(
            "crash", "critical" if event.severity == "S1" else "high", title,
            {"severity": event.severity, "reason": event.reason, "classification": event.classification,
             "crashed_sha": crashed_sha, "exception": tb.exc_type if tb else None,
             "signature": tb.signature if tb else None, "evidence": event.evidence,
             "traceback": tb.text[-3000:] if tb else None}, dedupe_key=key)
        if not created:
            return
        if self.notifier:
            self.notifier.incident(incident_id, title, self._crash_body(event, crashed_sha), ["crash"])
        if event.classification == "environment":
            if event.severity == "S1":
                await self.mitigate(incident_id, allow_rollback=False)
            # Even if a restart helped, the cause is still there; a human has to fix the environment.
            self.db.update_incident(incident_id, state="needs_human",
                                    summary=f"Environmental cause ({tb.env_marker if tb else 'unknown'}); no code change "
                                            "will fix it. The service was restarted if it was down.")
            return
        if event.severity == "S1":
            self.db.update_incident(incident_id, state="mitigating")
            await self.mitigate(incident_id)
        if event.classification == "code" and tb and tb.app_frames:
            asyncio.create_task(self._fix_forward_safe(incident_id, tb, crashed_sha), name=f"fix-forward-{incident_id}")

    async def mitigate(self, incident_id: int, allow_rollback: bool = True) -> None:
        """Step A — save production without the LLM: roll back to last-known-good, else restart."""
        if rules.auto_deploys_last_hour(self.db) >= rules.MAX_AUTO_PROD_DEPLOYS_PER_HOUR:
            self.db.update_incident(incident_id, state="needs_human",
                                    summary="Automatic deploy budget exhausted (3/hour); stopping to avoid a deploy loop.")
            return
        current = await asyncio.to_thread(self.prod.current_sha)
        lkg = rules.last_known_good(self.db)
        if allow_rollback and lkg and lkg["sha"] != current:
            result = await self.deploy_prod(lkg["sha"], "rollback", "crash", incident_id)
            if result is not None and result.ok:
                self.db.update_incident(incident_id, state="mitigated",
                                        summary=f"Rolled back {current[:12]} → last-known-good {lkg['sha'][:12]}.")
                return
        result = await self.act("crash", "restart_prod", self.prod.unit, {"sha": current[:12]},
                                lambda: asyncio.to_thread(self.prod.restart), incident_id)
        if result is not None and getattr(result, "ok", False):
            self.db.update_incident(incident_id, state="mitigated", summary="Restarted the service; health is green.")

    # ── fix-forward ────────────────────────────────────────────────────────
    async def _fix_forward_safe(self, incident_id: int, tb, crashed_sha: str) -> None:
        try:
            await self.fix_forward(incident_id, tb, crashed_sha)
        except Exception as exc:  # noqa: BLE001 — record on the incident instead of losing it
            log.exception("fix-forward for incident %s failed", incident_id)
            self.db.update_incident(incident_id, summary=f"Fix-forward error: {type(exc).__name__}: {exc}"[:400])

    async def fix_forward(self, incident_id: int, tb, crashed_sha: str) -> None:
        if self.mode("crash") == "off":
            return
        if rules.fix_attempted_recently(self.db, tb.signature):
            log.info("fix-forward for %s already attempted recently", tb.signature)
            return
        if self.sandbox is None:
            ok, why = False, "no sandbox configured"
        else:
            ok, why = await asyncio.to_thread(self.sandbox.available)
        if not ok:
            self.db.update_incident(incident_id, summary=f"Fix-forward skipped: sandbox unavailable ({why}).")
            return
        self.db.record_action("hotfix_attempt", tb.signature, {"incident": incident_id, "sha": crashed_sha[:12]},
                              self.mode("crash"), None, "started", incident_id)
        git_dir = self.paths["mirror"]
        await asyncio.to_thread(prguard.ensure_mirror, git_dir, self.cfg["github"]["repo"])
        if subprocess.run(["git", "--git-dir", git_dir, "cat-file", "-e", f"{crashed_sha}^{{commit}}"],
                          capture_output=True, check=False).returncode != 0:
            git_dir = os.path.join(self.prod.repo_dir, ".git")      # prod checkout still has the commit
        result = await hotfix.propose_and_verify(
            tb, git_dir, crashed_sha, self.gateway, self.sandbox, self.test_argv, self.sandbox_ro,
            self.cfg["crash"], self.paths["work"])
        attempts = "\n".join(f"- {a.stage}: {'ok' if a.ok else a.detail[:200]}" for a in result.attempts)
        if not result.ok:
            self.db.update_incident(incident_id, summary=f"No verified fix: {result.reason[:300]}")
            if self.notifier:
                self.notifier.incident(incident_id, "Fix-forward failed", f"Attempts:\n{attempts}")
            return
        await self.open_and_merge_hotfix(incident_id, tb, result)

    async def open_and_merge_hotfix(self, incident_id: int, tb, result) -> None:
        branch = f"flect/hotfix-{incident_id}"
        proposal = result.proposal
        clone = self.clone
        prod_branch = self.cfg["github"]["prod_branch"]

        def prepare_branch():
            clone.ensure_identity()
            clone.fetch()
            clone._run("checkout", "-B", branch, f"origin/{prod_branch}")
            ok, msg = hotfix._apply(str(clone.dir), proposal["patch_unified_diff"])
            if not ok:
                raise RuntimeError(f"patch does not apply to {prod_branch}: {msg}")
            hotfix._write_test(str(clone.dir), proposal)
            sha = clone.commit_all(f"Fix production crash: {tb.exc_type} in {proposal['root_cause_file']}\n\n"
                                   f"{proposal['diagnosis'][:1500]}\n\nFlect incident #{incident_id}")
            clone.push(f"{branch}:{branch}", force=True)
            return sha

        head_sha = await self.act("crash", "push_hotfix_branch", branch, {"incident": incident_id},
                                  lambda: asyncio.to_thread(prepare_branch), incident_id, github_write=True)
        if not head_sha:
            return
        body = hotfix.render_pr_body(incident_id, tb, proposal, result.attempts)
        number = await self.act("crash", "open_hotfix_pr", branch, {"base": prod_branch},
                                lambda: asyncio.to_thread(self.github.create_pr, prod_branch, branch,
                                                          f"[flect] Hotfix: {tb.exc_type} in {proposal['root_cause_file']}", body),
                                incident_id, github_write=True)
        if not number:
            return
        from flect.sources.github import PullRequest
        pr = PullRequest(number, f"Hotfix incident {incident_id}", body, head_sha, branch, self.cfg["github"]["repo"],
                         prod_branch, self.cfg["github"]["identity_name"], False)
        verdict = await prguard.review(pr, self.paths["mirror"], self.cfg["github"]["repo"], self.gateway, None, [],
                                       [], self.paths["work"], run_tests=False, prior_tests="passed")
        await self.publish_guard(pr, verdict)
        crash_open = bool(self.db.one("SELECT id FROM incidents WHERE id=? AND state!='resolved'", (incident_id,)))
        if not rules.can_auto_merge_hotfix("hotfix", prod_branch, prod_branch, crash_open, True, verdict.decision):
            self.db.update_incident(incident_id, state="needs_human",
                                    summary=f"Hotfix PR #{number} opened; guard decision {verdict.decision} — not auto-merged.")
            return
        merged = await self.act("crash", "merge_hotfix", f"PR#{number}", {"sha": head_sha[:12]},
                                lambda: asyncio.to_thread(self.github.merge_pr, number, head_sha), incident_id,
                                github_write=True)
        if not merged or not merged[0]:
            return
        await asyncio.to_thread(self.mirror_fetch)
        main_sha = await asyncio.to_thread(lambda: prguard._git(self.paths["mirror"], "rev-parse",
                                                                f"refs/heads/{prod_branch}").strip())
        self.db.set(f"gh:head:{prod_branch}", main_sha)      # this deploy is ours; the poller must not redo it
        res = await self.deploy_prod(main_sha, "hotfix", "crash", incident_id)
        if res is not None and res.ok:
            self.resolve_incident(incident_id, f"Hotfix PR #{number} merged and deployed ({main_sha[:12]}).")
            if self.cfg["github"]["feature_base"] != prod_branch:
                await self.act("cicd", "open_backmerge_pr", self.cfg["github"]["feature_base"], {"from": prod_branch},
                               lambda: asyncio.to_thread(self.github.create_pr, self.cfg["github"]["feature_base"],
                                                         prod_branch, f"[flect] Back-merge hotfix #{number} into "
                                                         f"{self.cfg['github']['feature_base']}",
                                                         f"Keeps `{self.cfg['github']['feature_base']}` in sync after hotfix #{number}."),
                               incident_id, github_write=True)

    def mirror_fetch(self) -> None:
        prguard.ensure_mirror(self.paths["mirror"], self.cfg["github"]["repo"])

    def _crash_body(self, event, sha: str) -> str:
        tb = event.traceback
        lines = [f"**Severity:** {event.severity} · **Classification:** {event.classification} · **Commit:** `{sha[:12]}`",
                 f"**Reason:** {event.reason}", ""]
        if tb:
            lines += [f"**Exception:** `{tb.exc_type}` {tb.exc_msg[:200]}", "", "```", tb.text[-2500:], "```"]
        lines += ["", f"Mode: crash={self.mode('crash')}. Plan: roll back to last-known-good, then attempt a "
                      "verified fix (regression test red→green in the sandbox)."]
        return "\n".join(lines)
