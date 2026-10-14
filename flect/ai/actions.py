"""What Flect AI may propose, and how each proposal is checked, described and run.

The model can only name an action from SPECS with schema-valid arguments. `check` then validates the proposal
against live state, both when it is proposed and again when the operator approves it. `run` executes it
through the policy engine's operator path (flect/policy/operator.py), which audits who approved it.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
from dataclasses import dataclass

from flect.config import CAPABILITIES, MODES
from flect.detect.dos import Allowlist
from flect.policy import rules

BY = "operator via Flect AI"

GUARD_NAME = {"prguard": "the PR guard", "dos": "the traffic shield", "crash": "crash recovery",
              "cicd": "CI/CD", "vapt": "release VAPT", "keys": "key and service checks"}
TTL_WORDS = {"15m": "15 minutes", "1h": "an hour", "24h": "24 hours"}

INCIDENT = {"type": "integer", "minimum": 1}
IP = {"type": "string", "maxLength": 45}
NOTE = {"type": "string", "maxLength": 200}


@dataclass(frozen=True)
class Spec:
    name: str
    risk: str                    # low | medium | high — shown on the approval card
    describe: str                # what the model is told the action does
    args: dict                   # JSON-schema properties of `args`


SPECS: list[Spec] = [
    Spec("recheck_services", "low",
         "Run every key, token, certificate and dependent-service check now (what the Keys page shows). "
         "Incidents whose checks pass again resolve automatically. Use after a human fixed a service or a token, "
         "or to confirm that something is still failing.", {}),
    Spec("restart_prod", "high",
         "Restart the production application itself (its systemd unit) and wait for its health checks to turn "
         "green. Causes a short outage. Only for production that is down, hung, very slow or throwing errors. It "
         "does NOT restart frs-backend, llama-server, ollama or any other dependency; Flect cannot restart those.",
         {}),
    Spec("rollback_prod", "high",
         "Deploy the last-known-good commit to production. Only when production runs a newer commit that is "
         "misbehaving.", {}),
    Spec("retry_fix", "medium",
         "Try again to fix a code crash incident: Flect writes a patch plus a regression test, proves in the "
         "sandbox that the test fails before and passes after, and opens a hotfix pull request (merged and "
         "deployed only if every gate passes). Takes several minutes.", {"incident_id": INCIDENT}),
    Spec("block_ip", "medium", "Block an IP address at the firewall for a while.",
         {"ip": IP, "ttl": {"type": "string", "enum": ["15m", "1h", "24h"]}}),
    Spec("unblock_ip", "low", "Remove an active block on an IP address.", {"ip": IP}),
    Spec("resolve_incident", "low",
         "Mark an open incident resolved with a short note; this also closes its GitHub issue. For false "
         "positives, or problems a human has already fixed.", {"incident_id": INCIDENT, "note": NOTE}),
    Spec("set_mode", "high",
         "Change a guard's mode: enforce (acts on its own), observe (only reports) or off.",
         {"capability": {"type": "string", "enum": list(CAPABILITIES)},
          "mode": {"type": "string", "enum": list(MODES)}}),
    Spec("pause_github_writes", "medium",
         "Stop Flect writing to GitHub (statuses, comments, merges, issues). Detection and IP blocking keep "
         "running.", {"reason": NOTE}),
    Spec("resume_github_writes", "low", "Allow GitHub writes again after a pause.", {}),
]
BY_NAME = {s.name: s for s in SPECS}


def catalog_text() -> str:
    """The ACTIONS section of the system prompt."""
    lines = []
    for s in SPECS:
        args = ", ".join(f"{k}" for k in s.args) or "no arguments"
        lines.append(f"- {s.name} ({args}; risk {s.risk}): {s.describe}")
    return "\n".join(lines)


def proposal_schema() -> dict:
    """One `actions` item: exactly one catalog action with its own argument object."""
    return {"anyOf": [
        {"type": "object", "additionalProperties": False, "required": ["action", "args", "why"],
         "properties": {"action": {"type": "string", "enum": [s.name]},
                        "args": {"type": "object", "additionalProperties": False, "required": list(s.args),
                                 "properties": s.args},
                        "why": {"type": "string", "maxLength": 240}}}
        for s in SPECS]}


def _ip(raw: str) -> str | None:
    try:
        return str(ipaddress.ip_address(str(raw).strip()))
    except ValueError:
        return None


async def check(live, name: str, args: dict) -> tuple[dict, str | None]:
    """Validate a proposal against live state. Returns (normalised args, None) or (args, why it cannot run)."""
    db, engine = live.db, live.engine
    if name not in BY_NAME:
        return args, f"unknown action {name!r}"
    if name in ("recheck_services", "restart_prod", "resume_github_writes", "pause_github_writes"):
        if name == "resume_github_writes" and not engine.writes_paused():
            return {}, "GitHub writes are not paused"
        if name == "pause_github_writes":
            if engine.writes_paused():
                return args, "GitHub writes are already paused"
            return {"reason": (args.get("reason") or "paused by the operator").strip()[:200]}, None
        return {}, None
    if name == "rollback_prod":
        lkg = rules.last_known_good(db)
        if not lkg:
            return {}, "there is no last-known-good commit to roll back to yet"
        current = await asyncio.to_thread(live.prod.current_sha)
        if current == lkg["sha"]:
            return {}, f"production already runs the last-known-good commit {lkg['sha'][:7]}"
        return {"sha": lkg["sha"], "from": current}, None
    if name in ("retry_fix", "resolve_incident"):
        iid = args.get("incident_id")
        row = db.one("SELECT id, kind, state, details FROM incidents WHERE id=?", (iid,)) if isinstance(iid, int) else None
        if not row:
            return args, f"there is no incident #{iid}"
        if row["state"] == "resolved":
            return args, f"incident #{iid} is already resolved"
        if name == "resolve_incident":
            note = (args.get("note") or "").strip() or "Resolved by the operator."
            return {"incident_id": iid, "note": note[:200]}, None
        details = json.loads(row["details"] or "{}")
        if row["kind"] != "crash" or not details.get("traceback"):
            return args, f"incident #{iid} is not a code crash with a traceback, so there is nothing to fix forward"
        return {"incident_id": iid}, None
    if name in ("block_ip", "unblock_ip"):
        ip = _ip(args.get("ip", ""))
        if not ip:
            return args, f"{args.get('ip')!r} is not an IP address"
        active = db.one("SELECT id FROM blocks WHERE ip=? AND active=1", (ip,))
        if name == "unblock_ip":
            return ({"ip": ip}, None) if active else ({"ip": ip}, f"{ip} is not blocked")
        if ip in Allowlist(live.cfg["dos"]["allowlist"]):
            return {"ip": ip, "ttl": args.get("ttl")}, f"{ip} is on the allowlist, so Flect never blocks it"
        if active:
            return {"ip": ip, "ttl": args.get("ttl")}, f"{ip} is already blocked"
        ttl = args.get("ttl") if args.get("ttl") in TTL_WORDS else "1h"
        return {"ip": ip, "ttl": ttl}, None
    if name == "set_mode":
        cap, mode = args.get("capability"), args.get("mode")
        if cap not in CAPABILITIES or mode not in MODES:
            return args, "unknown guard or mode"
        if engine.mode(cap) == mode:
            return args, f"{GUARD_NAME[cap]} is already in {mode} mode"
        return {"capability": cap, "mode": mode}, None
    return args, f"no check for {name}"


def title(live, name: str, args: dict) -> str:
    """Short label for the approval card."""
    target = live.cfg["target"]["name"].upper()
    return {
        "recheck_services": lambda: "Run every key and service check now",
        "restart_prod": lambda: f"Restart {target} ({live.cfg['target']['prod_unit']})",
        "rollback_prod": lambda: f"Roll production back to {str(args.get('sha', ''))[:7] or 'last known good'}",
        "retry_fix": lambda: f"Retry the fix for incident #{args.get('incident_id')}",
        "block_ip": lambda: f"Block {args.get('ip')} for {TTL_WORDS.get(args.get('ttl'), args.get('ttl'))}",
        "unblock_ip": lambda: f"Unblock {args.get('ip')}",
        "resolve_incident": lambda: f"Resolve incident #{args.get('incident_id')}",
        "set_mode": lambda: f"Set {GUARD_NAME.get(args.get('capability'), args.get('capability'))} to {args.get('mode')}",
        "pause_github_writes": lambda: "Pause GitHub writes",
        "resume_github_writes": lambda: "Resume GitHub writes",
    }.get(name, lambda: name)()


def starting(live, name: str, args: dict) -> str:
    """What Flect says as it starts the action."""
    target = live.cfg["target"]["name"].upper()
    return {
        "recheck_services": "Running every check now.",
        "restart_prod": f"Restarting {target}. It will be unavailable for a moment.",
        "rollback_prod": f"Rolling production back to commit {str(args.get('sha', ''))[:7]}.",
        "retry_fix": f"Asking the crash pipeline for a verified fix to incident {args.get('incident_id')}. "
                     "This takes a few minutes.",
        "block_ip": f"Blocking {args.get('ip')}.",
        "unblock_ip": f"Unblocking {args.get('ip')}.",
        "resolve_incident": f"Resolving incident {args.get('incident_id')}.",
        "set_mode": f"Switching {GUARD_NAME.get(args.get('capability'), '')} to {args.get('mode')}.",
        "pause_github_writes": "Pausing GitHub writes.",
        "resume_github_writes": "Resuming GitHub writes.",
    }.get(name, "Working on it.")


def _names(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


async def run(live, name: str, args: dict) -> tuple[bool, str]:
    """Execute an approved proposal. Returns (ok, what Flect says about the result)."""
    e, db = live.engine, live.db
    target = live.cfg["target"]["name"].upper()
    if name == "recheck_services":
        if e.mode("keys") == "off":
            return False, "Key and service checks are switched off, so nothing was updated."
        results = await e.operator_recheck(BY)
        failing = [r.name for r in results if r.probe_ok is False]
        if not failing:
            return True, f"All {len(results)} checks pass."
        return True, f"Checks done. {_names(failing)} {'is' if len(failing) == 1 else 'are'} still failing."
    if name == "restart_prod":
        r = await e.operator_restart_prod(BY)
        if r is None:
            return False, "The restart command failed. The audit log has the error."
        if getattr(r, "ok", False):
            return True, f"{target} restarted and is answering health checks."
        return False, f"{target} restarted but is not healthy yet: {r.detail}."
    if name == "rollback_prod":
        sha, r = await e.operator_rollback(BY)
        if r is None:
            return False, f"The rollback to {sha[:7]} did not run. The audit log has the details."
        if r.ok:
            return True, f"Rolled back to commit {sha[:7]}. Production is healthy."
        return False, f"The rollback to {sha[:7]} did not come up healthy: {r.detail}."
    if name == "retry_fix":
        row = await e.operator_retry_fix(args["incident_id"], BY) or {}
        summary = (row.get("summary") or "").strip()
        ok = row.get("state") == "resolved" or "PR #" in summary
        return ok, f"The fix attempt for incident {args['incident_id']} finished. {summary}".strip()
    if name == "block_ip":
        ok = await e.operator_block(args["ip"], args["ttl"], BY)
        return ok, (f"{args['ip']} is blocked for {TTL_WORDS[args['ttl']]}." if ok
                    else f"I could not block {args['ip']}; the firewall helper did not accept it.")
    if name == "unblock_ip":
        ok = await e.operator_unblock(args["ip"], BY)
        return ok, f"{args['ip']} is unblocked." if ok else f"The firewall would not remove the block on {args['ip']}."
    if name == "resolve_incident":
        e.operator_resolve(args["incident_id"], args["note"], BY)
        return True, f"Incident {args['incident_id']} is resolved."
    if name == "set_mode":
        e.operator_set_mode(args["capability"], args["mode"], BY)
        return True, f"{GUARD_NAME[args['capability']].capitalize()} is now in {args['mode']} mode."
    if name == "pause_github_writes":
        e.operator_pause(args["reason"], BY)
        return True, "GitHub writes are paused."
    if name == "resume_github_writes":
        e.operator_resume(BY)
        return True, "GitHub writes are back on."
    return False, f"I don't know how to run {name}."
