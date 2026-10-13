"""Crash fix-forward: ask the model for a minimal patch plus a regression test, then prove it.

Gates (all must pass before the policy engine may open/merge a hotfix PR):
  - classification == code, patch within size limits, no forbidden paths
  - patch applies cleanly to the deployed commit
  - regression test FAILS on the deployed code and PASSES with the patch (sandboxed, no network)
  - the full test suite passes with the patch (sandboxed)
The model gets the failure output and may retry up to `fix_attempts` times.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from flect.analyze.prguard import export_tree
from flect.gateway.llm import P_CRASH, build_messages

FIX_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["classification", "diagnosis", "root_cause_file", "confidence", "patch_unified_diff",
                 "regression_test_path", "regression_test_code"],
    "properties": {
        "classification": {"enum": ["code", "environment", "dependency", "data", "unknown"]},
        "diagnosis": {"type": "string", "maxLength": 2000},
        "root_cause_file": {"type": "string", "maxLength": 300},
        "confidence": {"enum": ["low", "medium", "high"]},
        "patch_unified_diff": {"type": "string", "maxLength": 40000},
        "regression_test_path": {"type": "string", "pattern": "^tests/test_flect_[a-z0-9_]+\\.py$"},
        "regression_test_code": {"type": "string", "maxLength": 12000},
    },
}
FIX_INSTRUCTIONS = (
    "A production Python service crashed. Using the traceback and source excerpts, find the root cause and "
    "propose the smallest safe fix as a unified diff (paths relative to the repository root, `a/` and `b/` "
    "prefixes, correct hunk headers). Do not refactor, do not change unrelated behaviour, do not touch tests "
    "other than the new regression test, deployment files or authentication code. Also write one pytest file at "
    "tests/test_flect_<name>.py that reproduces the crash: it must fail on the current code and pass once the "
    "patch is applied, and must not need network, GPU or external services. If the cause is environmental "
    "(disk, memory, ports, unreachable services, missing files) set classification accordingly and leave the "
    "patch empty."
)


@dataclass
class FixAttempt:
    ok: bool
    stage: str
    detail: str
    proposal: dict | None = None


@dataclass
class FixResult:
    ok: bool
    proposal: dict | None
    attempts: list[FixAttempt] = field(default_factory=list)
    reason: str = ""


def patch_stats(diff: str) -> tuple[list[str], int]:
    files = sorted(set(re.findall(r"^\+\+\+ b/(\S+)", diff, re.M)) | set(re.findall(r"^--- a/(\S+)", diff, re.M)))
    changed = sum(1 for line in diff.splitlines()
                  if (line.startswith("+") or line.startswith("-")) and not line.startswith(("+++", "---")))
    return files, changed


def check_limits(proposal: dict, cfg: dict) -> str | None:
    if proposal["classification"] != "code":
        return f"model classified the crash as {proposal['classification']}; no code fix"
    diff = proposal["patch_unified_diff"]
    if not diff.strip():
        return "empty patch"
    files, changed = patch_stats(diff)
    if not files:
        return "patch has no file headers"
    if len(files) > cfg["hotfix_max_files"]:
        return f"patch touches {len(files)} files (limit {cfg['hotfix_max_files']})"
    if changed > cfg["hotfix_max_lines"]:
        return f"patch changes {changed} lines (limit {cfg['hotfix_max_lines']})"
    for f in files:
        if f.startswith("/") or ".." in Path(f).parts:
            return f"unsafe path in patch: {f}"
        if any(f == p or f.startswith(p) for p in cfg["hotfix_forbidden_paths"]):
            return f"patch touches forbidden path {f}"
        if f.startswith("tests/"):
            return f"patch may not modify existing tests ({f})"
    return None


def source_context(tree: str, traceback, max_chars: int) -> dict:
    """Excerpts around every application frame, numbered so the model can write accurate hunks."""
    ctx = {}
    for frame in traceback.app_frames[-6:]:
        path = Path(tree) / frame["rel"]
        try:
            lines = path.read_text().splitlines()
        except OSError:
            continue
        lo, hi = max(0, frame["line"] - 40), min(len(lines), frame["line"] + 40)
        numbered = "\n".join(f"{n + 1:5d}| {lines[n]}" for n in range(lo, hi))
        ctx[f"{frame['rel']}:{lo + 1}-{hi}"] = numbered
    budget = max_chars // 2
    out, used = {}, 0
    for key, text in reversed(list(ctx.items())):      # innermost frames first
        if used + len(text) > budget:
            break
        out[key] = text
        used += len(text)
    return out


def _apply(tree: str, diff: str, check_only: bool = False) -> tuple[bool, str]:
    args = ["git", "apply", "--recount", "--whitespace=nowarn", "-p1"]
    if check_only:
        args.append("--check")
    # The tree is a plain directory; stop git from discovering an enclosing repository (e.g. ~/flect).
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": os.path.dirname(os.path.abspath(tree))}
    res = subprocess.run(args, cwd=tree, input=diff, capture_output=True, text=True, timeout=60, check=False, env=env)
    return res.returncode == 0, (res.stderr or res.stdout).strip()[:1500]


def _write_test(tree: str, proposal: dict) -> None:
    dest = Path(tree) / proposal["regression_test_path"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(proposal["regression_test_code"])


def verify(proposal: dict, deployed_tree: str, sandbox, test_argv: list[str], ro_binds: list[str],
           cfg: dict, workdir: str) -> FixAttempt:
    why = check_limits(proposal, cfg)
    if why:
        return FixAttempt(False, "limits", why, proposal)
    with tempfile.TemporaryDirectory(prefix="flect-hotfix-", dir=workdir) as tmp:
        old, new = os.path.join(tmp, "old"), os.path.join(tmp, "new")
        shutil.copytree(deployed_tree, old, symlinks=True)
        shutil.copytree(deployed_tree, new, symlinks=True)
        ok, msg = _apply(new, proposal["patch_unified_diff"])
        if not ok:
            return FixAttempt(False, "apply", f"patch does not apply: {msg}", proposal)
        _write_test(old, proposal)
        _write_test(new, proposal)
        single = [*test_argv, proposal["regression_test_path"]]
        before = sandbox.run(old, single, ro_binds)
        if before.returncode is None:
            return FixAttempt(False, "sandbox", before.output[-1500:], proposal)
        if before.ok:
            return FixAttempt(False, "regression_red", "regression test PASSES on the deployed code, so it does not "
                              "reproduce the crash:\n" + before.output[-1500:], proposal)
        after = sandbox.run(new, single, ro_binds)
        if not after.ok:
            return FixAttempt(False, "regression_green", "regression test still FAILS with the patch:\n"
                              + after.output[-1500:], proposal)
        full = sandbox.run(new, test_argv, ro_binds)
        if not full.ok:
            return FixAttempt(False, "suite", "full test suite fails with the patch:\n" + full.output[-1500:], proposal)
    return FixAttempt(True, "verified", "regression test red→green; full suite green", proposal)


async def propose_and_verify(traceback, mirror: str, deployed_sha: str, gateway, sandbox, test_argv: list[str],
                             ro_binds: list[str], cfg: dict, workdir: str, recent_diff: str = "") -> FixResult:
    import asyncio
    result = FixResult(False, None)
    with tempfile.TemporaryDirectory(prefix="flect-deployed-", dir=workdir) as tree:
        await asyncio.to_thread(export_tree, mirror, deployed_sha, tree)
        sources = source_context(tree, traceback, gateway.cfg["max_prompt_chars"]["crash"])
        feedback = ""
        for attempt in range(int(cfg["fix_attempts"])):
            untrusted = {"traceback": traceback.text, "sources": sources}
            if recent_diff:
                untrusted["recent_changes"] = recent_diff
            if feedback:
                untrusted["previous_attempt_failed"] = feedback
            msgs = build_messages("crash_fix", [], {"deployed_sha": deployed_sha, "exception": traceback.exc_type,
                                                     "attempt": attempt + 1},
                                  untrusted, FIX_INSTRUCTIONS, gateway.cfg["max_prompt_chars"]["crash"])
            try:
                proposal = await gateway.ask("crash_fix", P_CRASH, msgs, FIX_SCHEMA, ref=traceback.signature)
            except Exception as exc:  # noqa: BLE001
                result.attempts.append(FixAttempt(False, "llm", f"{type(exc).__name__}: {exc}"[:300]))
                result.reason = "model unavailable"
                return result
            outcome = await asyncio.to_thread(verify, proposal, tree, sandbox, test_argv, ro_binds, cfg, workdir)
            result.attempts.append(outcome)
            if outcome.ok:
                result.ok, result.proposal = True, proposal
                return result
            if outcome.stage in {"limits", "sandbox"} and proposal.get("classification") != "code":
                result.reason = outcome.detail
                return result
            feedback = f"stage={outcome.stage}: {outcome.detail}"
    result.reason = result.attempts[-1].detail if result.attempts else "no attempts"
    return result


def render_pr_body(incident_id: int, traceback, proposal: dict, attempts: list[FixAttempt]) -> str:
    files, changed = patch_stats(proposal["patch_unified_diff"])
    return "\n".join([
        f"## 🚑 Flect hotfix for production crash (incident #{incident_id})",
        "",
        f"**Exception:** `{traceback.exc_type}` — {traceback.exc_msg[:200]}",
        f"**Signature:** `{traceback.signature}`",
        "",
        "### Diagnosis",
        proposal["diagnosis"],
        "",
        "### Change",
        f"- Files: {', '.join(f'`{f}`' for f in files)} ({changed} lines)",
        f"- Regression test: `{proposal['regression_test_path']}`",
        f"- Model confidence: {proposal['confidence']}",
        "",
        "### Verification (sandboxed, no network)",
        "- Regression test fails on the deployed commit ✅",
        "- Regression test passes with this patch ✅",
        "- Full test suite passes with this patch ✅",
        f"- Attempts: {len(attempts)}",
        "",
        "_Production was already rolled back or restarted before this PR was opened. "
        "Flect merges this automatically only because production was crashing._",
    ])
