"""Deterministic rules and thresholds used by the policy engine. No I/O except DB reads."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

TTL_DELTAS = {"15m": timedelta(minutes=15), "1h": timedelta(hours=1), "24h": timedelta(hours=24)}


# ── DoS ───────────────────────────────────────────────────────────────────
def offence_count(db, ip: str, hours: int = 24) -> int:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    row = db.one("SELECT COUNT(*) AS n FROM blocks WHERE ip=? AND created_ts > ?", (ip, since))
    return row["n"] if row else 0


def ttl_for_offence(ladder: list[str], offence: int) -> str:
    return ladder[min(offence, len(ladder)) - 1]


def ttl_delta(ttl: str) -> timedelta:
    return TTL_DELTAS[ttl]


def ttl_ceiling(remaining: timedelta) -> str:
    for ttl in ("15m", "1h", "24h"):
        if remaining <= TTL_DELTAS[ttl]:
            return ttl
    return "24h"


# ── keys ──────────────────────────────────────────────────────────────────
def key_alert_level(kind: str, days_left: float | None, probe_ok: bool | None, warn_days: list[int],
                    cert_warn_days: int) -> str:
    if probe_ok is False:
        return "failing"
    if days_left is None:
        return "ok"
    if days_left <= 0:
        return "expired"
    thresholds = sorted(set(warn_days) | ({cert_warn_days} if kind == "tls_cert" else set()))
    for d in thresholds:
        if days_left <= d:
            return f"T-{d}d"
    return "ok"


def key_runbook(kind: str) -> str:
    return {
        "github_pat": ("**Rotate:** create a new fine-grained PAT for `soczap` scoped to `soczap/flect` and "
                       "`soczap/Computer_Vision` (Contents, Pull requests, Commit statuses, Issues: read/write; "
                       "Administration: read/write for branch protection), then run "
                       "`gh auth login --with-token < token.txt`. Flect pauses GitHub writes while the token is "
                       "expired; detection and IP blocking keep running."),
        "tls_cert": ("**Renew** the certificate and key at the listed path (VIGIL reads `VIGIL_TLS_CERT` / "
                     "`VIGIL_TLS_KEY`), then `systemctl --user restart vigil`."),
        "jwt": "**Rotate** the token at the listed env key and restart the service that reads it.",
        "service": ("**Check** the dependent service is running; VIGIL degrades or crashes when it is "
                    "unreachable."),
    }.get(kind, "")


# ── crash / deploy ────────────────────────────────────────────────────────
def auto_deploys_last_hour(db) -> int:
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
    row = db.one("SELECT COUNT(*) AS n FROM deployments WHERE env='prod' AND trigger IN ('rollback','hotfix') "
                 "AND started_ts > ?", (since,))
    return row["n"] if row else 0


MAX_AUTO_PROD_DEPLOYS_PER_HOUR = 3


def fix_attempted_recently(db, signature: str, hours: int = 6) -> bool:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    row = db.one("SELECT COUNT(*) AS n FROM actions WHERE decision='hotfix_attempt' AND target=? AND ts > ?",
                 (signature, since))
    return bool(row and row["n"])


def in_post_deploy_watch(db, sha: str, minutes: float) -> dict | None:
    """Flect's own production deploy of `sha` (a hotfix, or a release a human merged) if it happened within the
    last `minutes`. A crash in that window is treated as a regression of that deploy."""
    since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    return db.one("SELECT * FROM deployments WHERE env='prod' AND sha=? AND trigger IN ('hotfix','human_merge') "
                  "AND started_ts > ? ORDER BY id DESC LIMIT 1", (sha, since))


def last_known_good(db) -> dict | None:
    return db.one("SELECT * FROM deployments WHERE env='prod' AND state='lkg' ORDER BY id DESC LIMIT 1")


def can_auto_merge_feature(pr_kind: str, base: str, feature_base: str, decision: str, tests: str) -> bool:
    """Feature PRs merge automatically only into the UAT branch, and only when every gate is green."""
    return pr_kind == "feature" and base == feature_base and decision == "pass" and tests == "passed"


def can_auto_merge_hotfix(pr_kind: str, base: str, prod_branch: str, crash_open: bool, verified: bool,
                          guard_decision: str) -> bool:
    """The ONLY autonomous merge into production: a verified fix for an open production crash."""
    return (pr_kind == "hotfix" and base == prod_branch and crash_open and verified
            and guard_decision in ("pass", "needs_human_tests_only"))
