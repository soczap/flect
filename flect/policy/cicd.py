"""CI/CD flows driven by the agent: PR guard → merge to UAT → deploy UAT → VAPT on release PRs →
(human merges release) → deploy prod → watch."""
from __future__ import annotations

import asyncio
import json
import logging
import tempfile

from flect.analyze import prguard, vapt
from flect.db import now
from flect.policy import rules

log = logging.getLogger("flect.cicd")

STATUS = {"pass": "success", "block": "failure", "needs_human": "failure", "error": "error"}


class CicdFlows:
    # ── pull requests ──────────────────────────────────────────────────────
    async def on_pr(self, pr) -> None:
        repo = self.cfg["github"]["repo"]
        if self.mode("prguard") == "off":
            return
        self.db.execute("INSERT OR REPLACE INTO prs(repo,number,head_sha,base,kind,state,title,updated_ts) "
                        "VALUES(?,?,?,?,?,?,?,?)", (repo, pr.number, pr.head_sha, pr.base_ref, pr.kind, "scanning",
                                                    pr.title[:200], now()))
        if pr.kind == "hotfix" and pr.author == self.cfg["github"]["identity_name"] and pr.head_ref.startswith("flect/"):
            return  # Flect's own hotfix PRs are guarded inside the crash flow
        await self.github_status(pr.head_sha, "flect/pr-guard", "pending", "Flect is reviewing this PR")
        try:
            verdict = await prguard.review(pr, self.paths["mirror"], repo, self.gateway, self.sandbox,
                                           self.sandbox_ro, self.test_argv, self.paths["work"])
        except Exception as exc:  # noqa: BLE001
            log.exception("PR guard failed for #%s", pr.number)
            self.db.execute("UPDATE prs SET state='error', updated_ts=? WHERE repo=? AND number=? AND head_sha=?",
                            (now(), repo, pr.number, pr.head_sha))
            await self.github_status(pr.head_sha, "flect/pr-guard", "error", f"guard error: {type(exc).__name__}")
            return
        await self.publish_guard(pr, verdict)
        await self.after_guard(pr, verdict)

    async def publish_guard(self, pr, verdict) -> None:
        repo = self.cfg["github"]["repo"]
        self.db.execute("UPDATE prs SET state=?, risk=?, llm_verdict=?, statuses=?, updated_ts=? "
                        "WHERE repo=? AND number=? AND head_sha=?",
                        ({"pass": "passed", "block": "blocked"}.get(verdict.decision, verdict.decision), verdict.risk,
                         json.dumps(verdict.llm) if verdict.llm else None,
                         json.dumps({"decision": verdict.decision, "tests": verdict.tests, "reasons": verdict.reasons}),
                         now(), repo, pr.number, pr.head_sha))
        for f in verdict.findings:
            self.db.execute("INSERT OR REPLACE INTO findings(id,scope,ref,rule_id,severity,title,file,line,evidence,created_ts) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (f"{pr.number}:{pr.head_sha[:12]}:{f.id}"[:300], "pr", str(pr.number), f.rule_id, f.severity,
                             f.title[:300], f.file, f.line, f.detail[:500], now()))
        comment = prguard.render_comment(pr, verdict, self.mode("prguard"))
        if self.notifier:
            self.notifier.save_report("prguard", f"pr{pr.number}-{pr.head_sha[:12]}", comment, pr.head_sha, pr.number,
                                      verdict.max_severity())
        secrets = any(f.rule_id.startswith("SECRET-") for f in verdict.findings)
        await self.github_status(pr.head_sha, "flect/pr-guard", STATUS[verdict.decision],
                                 f"{verdict.decision} (risk {verdict.risk})")
        await self.github_status(pr.head_sha, "flect/secrets", "failure" if secrets else "success",
                                 "new credential-like material" if secrets else "no new secrets")
        await self.github_status(pr.head_sha, "flect/sandbox-tests",
                                 {"passed": "success", "failed": "failure"}.get(verdict.tests, "pending"),
                                 f"tests {verdict.tests}")
        await self.act("prguard", "comment_pr", f"PR#{pr.number}", {"decision": verdict.decision},
                       lambda: self.github.comment(pr.number, comment), github_write=True)
        if verdict.decision == "block":
            await self.act("prguard", "label_pr", f"PR#{pr.number}", {"label": "flect:blocked"},
                           lambda: self.github.add_labels(pr.number, ["flect:blocked"]), github_write=True)
            if verdict.risk == "critical":
                await self.act("prguard", "close_pr", f"PR#{pr.number}", {"risk": "critical"},
                               lambda: self.github.close_pr(pr.number, "Closed by Flect: critical risk. See the review above."),
                               github_write=True)
        elif verdict.decision == "needs_human":
            await self.act("prguard", "label_pr", f"PR#{pr.number}", {"label": "flect:needs-human"},
                           lambda: self.github.add_labels(pr.number, ["flect:needs-human"]), github_write=True)

    async def on_human_approval(self, pr, login: str) -> None:
        """Override a needs-human verdict. Never applies to blocked PRs; never merges on its own."""
        repo = self.cfg["github"]["repo"]
        row = self.db.one("SELECT state, statuses FROM prs WHERE repo=? AND number=? AND head_sha=?",
                          (repo, pr.number, pr.head_sha))
        if not row or row["state"] != "needs_human":
            return
        tests = json.loads(row["statuses"] or "{}").get("tests")
        await self.github_status(pr.head_sha, "flect/pr-guard", "success", f"approved by @{login} (was needs-human)")
        await self.github_status(pr.head_sha, "flect/sandbox-tests", "success",
                                 "tests passed" if tests == "passed" else f"waived by @{login}")
        self.db.execute("UPDATE prs SET state='approved', updated_ts=? WHERE repo=? AND number=? AND head_sha=?",
                        (now(), repo, pr.number, pr.head_sha))
        await self.act("prguard", "comment_pr", f"PR#{pr.number}", {"approved_by": login},
                       lambda: self.github.comment(pr.number, f"### ✅ Flect: approved by @{login}\n\nThe needs-human "
                                                   f"verdict for `{pr.head_sha[:12]}` was overridden; Flect's checks are "
                                                   "now green. Merge when ready. A new push will be reviewed again."),
                       github_write=True)

    async def after_guard(self, pr, verdict) -> None:
        gh = self.cfg["github"]
        if rules.can_auto_merge_feature(pr.kind, pr.base_ref, gh["feature_base"], verdict.decision, verdict.tests):
            merged = await self.act("prguard", "merge_to_uat", f"PR#{pr.number}", {"sha": pr.head_sha[:12]},
                                    lambda: asyncio.to_thread(self.github.merge_pr, pr.number, pr.head_sha),
                                    github_write=True)
            if merged and merged[0]:
                self.db.execute("UPDATE prs SET state='merged' WHERE repo=? AND number=? AND head_sha=?",
                                (gh["repo"], pr.number, pr.head_sha))
        if pr.kind == "release" and verdict.decision != "block":
            asyncio.create_task(self.release_vapt(pr), name=f"vapt-{pr.number}")

    async def github_status(self, sha: str, context: str, state: str, description: str) -> None:
        await self.act("prguard", f"status:{context}", sha[:12], {"state": state, "description": description},
                       lambda: asyncio.to_thread(self.github.set_status, sha, context, state, description),
                       github_write=True)

    # ── branch moves (merges) ──────────────────────────────────────────────
    async def on_branch_move(self, branch: str, old: str, new: str) -> None:
        gh = self.cfg["github"]
        if branch == gh["prod_branch"]:
            # A human merged into prod (release). Deploy it; the deploy rolls back on failed health.
            await self.deploy_prod(new, "human_merge", "cicd")
        elif branch == gh["feature_base"]:
            await self.deploy_uat(new)

    async def deploy_uat(self, sha: str):
        if self.uat is None:
            return None
        async with self.deploy_lock["uat"]:
            result = await self.act("cicd", "deploy_uat", sha[:12], {"sha": sha[:12]},
                                    lambda: asyncio.to_thread(self.uat.deploy, sha, 20))
            if result is not None:
                self.record_deployment("uat", sha, result.previous_sha, "uat_merge",
                                       "healthy" if result.ok else "failed", result.detail)
            return result

    # ── VAPT on release PRs ────────────────────────────────────────────────
    async def release_vapt(self, pr) -> None:
        t = self.cfg["target"]
        if self.mode("vapt") == "off":
            return
        await self.github_status(pr.head_sha, "flect/vapt", "pending", "VAPT running against UAT")
        uat_note = ""
        if self.uat is not None and self.mode("cicd") == "enforce":
            res = await self.deploy_uat(pr.head_sha)
            if res is None or not res.ok:
                uat_note = f"UAT deploy of {pr.head_sha[:12]} did not become healthy; dynamic checks may fail."
        elif self.uat is None:
            uat_note = "UAT instance not configured; dynamic checks skipped."
        with tempfile.TemporaryDirectory(prefix=f"flect-vapt-{pr.number}-", dir=self.paths["work"]) as tree:
            await asyncio.to_thread(self.mirror_fetch)
            await asyncio.to_thread(prguard.export_tree, self.paths["mirror"], pr.head_sha, tree)
            report = await vapt.run_vapt(t["uat_url"], t["uat_url"], t["protected_ports"], tree, pr.head_sha,
                                         self.gateway, osv=bool(self.cfg.data.get("vapt", {}).get("osv", False)))
        if uat_note:
            report.coverage.append({"name": "uat", "status": "partial", "detail": uat_note})
        md = vapt.render(report)
        if self.notifier:
            self.notifier.save_report("vapt", f"pr{pr.number}-{pr.head_sha[:12]}", md, pr.head_sha, pr.number,
                                      report.max_severity())
        await self.act("vapt", "comment_vapt", f"PR#{pr.number}", {"max": report.max_severity()},
                       lambda: self.github.comment(pr.number, md), github_write=True)
        await self.act("vapt", "status:flect/vapt", pr.head_sha[:12], {"passed": report.passed()},
                       lambda: asyncio.to_thread(self.github.set_status, pr.head_sha, "flect/vapt",
                                                 "success" if report.passed() else "failure",
                                                 f"VAPT {'passed' if report.passed() else 'failed'}: max {report.max_severity()}"),
                       github_write=True)
