import asyncio
from datetime import datetime, timedelta, timezone

from flect.detect.dos import BlockRequest
from flect.policy.engine import Engine
from flect.sources.keys import KeyStatus


class FakeNft:
    def __init__(self):
        self.blocked = []

    def block(self, ip, ttl):
        self.blocked.append((ip, ttl))

    def unblock(self, ip):
        self.blocked = [b for b in self.blocked if b[0] != ip]

    def flood(self, on, rate=50):
        self.blocked.append(("flood", on))


def run(c):
    return asyncio.run(c)


def req(ip="203.0.113.9"):
    return BlockRequest(ip, "DOS-RATE-001", "30 req/s", {"rate": 30})


def test_observe_mode_records_but_does_not_block(cfg, db):
    nft = FakeNft()
    e = Engine(cfg, db, nft=nft)
    run(e.on_block_request(req()))
    assert nft.blocked == []
    a = db.one("SELECT * FROM actions WHERE decision='block_ip'")
    assert a["mode"] == "observe" and a["result"].startswith("would_do")
    assert db.one("SELECT active, mode FROM blocks") == {"active": 0, "mode": "observe"}


def test_enforce_mode_blocks_with_escalating_ttl(cfg, db):
    nft = FakeNft()
    db.set("mode:dos", "enforce")
    e = Engine(cfg, db, nft=nft)
    run(e.on_block_request(req()))
    run(e.on_block_request(req()))
    run(e.on_block_request(req()))
    run(e.on_block_request(req()))
    assert [t for _, t in nft.blocked] == ["15m", "1h", "24h", "24h"]
    assert db.verify_audit_chain()
    run(e.unblock("203.0.113.9"))
    assert db.one("SELECT COUNT(*) n FROM blocks WHERE active=1")["n"] == 0


def test_github_writes_pause_when_token_expired(cfg, db):
    db.set("mode:prguard", "enforce")
    e = Engine(cfg, db)
    expired = KeyStatus("github-pat (gh, soczap)", "github_pat", "gh", datetime.now(timezone.utc) - timedelta(hours=1), True)
    run(e.on_key_results([expired]))
    assert e.writes_paused()
    called = []
    run(e.act("prguard", "comment_pr", "PR#1", {}, lambda: called.append(1), github_write=True))
    assert called == []
    ok = KeyStatus("github-pat (gh, soczap)", "github_pat", "gh", datetime.now(timezone.utc) + timedelta(days=60), True)
    run(e.on_key_results([ok]))
    assert e.writes_paused() is None
    run(e.act("prguard", "comment_pr", "PR#1", {}, lambda: called.append(1), github_write=True))
    assert called == [1]


def test_key_alert_opens_incident_once(cfg, db):
    e = Engine(cfg, db)
    soon = KeyStatus("github-pat (gh, soczap)", "github_pat", "gh", datetime.now(timezone.utc) + timedelta(days=1.5), True)
    run(e.on_key_results([soon]))
    run(e.on_key_results([soon]))
    rows = db.all("SELECT title, severity FROM incidents WHERE kind='expiry'")
    assert len(rows) == 1 and rows[0]["title"].endswith("T-3d")


def test_hotfix_merge_rule_is_narrow():
    from flect.policy.rules import can_auto_merge_feature, can_auto_merge_hotfix
    assert can_auto_merge_hotfix("hotfix", "main", "main", True, True, "pass")
    assert not can_auto_merge_hotfix("hotfix", "main", "main", False, True, "pass")   # no open crash
    assert not can_auto_merge_hotfix("feature", "main", "main", True, True, "pass")   # not a hotfix
    assert not can_auto_merge_hotfix("hotfix", "main", "main", True, True, "needs_human")
    assert can_auto_merge_feature("feature", "uat", "uat", "pass", "passed")
    assert not can_auto_merge_feature("feature", "main", "uat", "pass", "passed")     # never straight to prod
    assert not can_auto_merge_feature("feature", "uat", "uat", "pass", "unavailable")
