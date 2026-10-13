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
    db.set("mode:keys", "enforce")
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


def test_notifier_respects_pause(db, tmp_path):
    from flect.actuators.notify import Notifier

    class GH:
        opened = []

        def open_issue(self, title, body, labels):
            self.opened.append(title)
            return 42

    gh = GH()
    n = Notifier(db, tmp_path / "r", gh, True, paused=lambda: db.get("writes_paused"))
    i, _ = db.open_incident("expiry", "high", "t", {})
    db.set("writes_paused", "maintenance")
    assert n.incident(i, "t", "b") is None and gh.opened == []
    db.set("writes_paused", None)
    assert n.incident(i, "t", "b") == 42 and gh.opened == ["[flect] t"]
    assert n.incident(i, "t", "b") == 42 and len(gh.opened) == 1          # one issue per incident


def test_env_scan_registers_only_secret_settings(tmp_path):
    from flect import redact
    from flect.sources.keys import jwt_in_env_file
    env = tmp_path / ".env"
    env.write_text("VIGIL_FRS_URL=https://127.0.0.1:8000\nVIGIL_PORT=8090\nVIGIL_JWT_SECRET=abcdef123456789xyz\n")
    jwt_in_env_file(str(env))
    out = redact.redact("url https://127.0.0.1:8000 port 8090 secret abcdef123456789xyz")
    assert "https://127.0.0.1:8000" in out and "8090" in out and "abcdef123456789xyz" not in out


def test_uat_stops_after_deploy_when_on_demand(cfg, db):
    from flect.actuators.deploy import DeployResult
    db.set("mode:cicd", "enforce")

    class UAT:
        stopped = 0
        def deploy(self, sha, verify_s=60):
            return DeployResult(True, sha, "a" * 40, "healthy")
        def stop(self):
            UAT.stopped += 1
            return True
    e = Engine(cfg, db, uat=UAT())
    run(e.on_branch_move("uat", "a" * 40, "b" * 40))
    assert UAT.stopped == 1
    assert db.one("SELECT env, state FROM deployments") == {"env": "uat", "state": "healthy"}


def pat(days=None, ok=True):
    exp = datetime.now(timezone.utc) + timedelta(days=days) if days is not None else None
    return KeyStatus("github-pat (gh, soczap)", "github_pat", "gh", exp, ok)


def test_keys_observe_reports_but_does_not_pause(cfg, db):
    e = Engine(cfg, db)                                   # keys ships in observe
    for _ in range(3):
        run(e.on_key_results([pat(days=-1)]))
    assert e.writes_paused() is None
    rows = db.all("SELECT mode, result FROM actions WHERE decision='pause_github_writes'")
    assert len(rows) == 1 and rows[0]["mode"] == "observe"        # once per level change, not every check
    assert db.one("SELECT title FROM incidents")["title"].endswith("expired")


def test_keys_off_skips_checks(cfg, db):
    db.set("mode:keys", "off")
    e = Engine(cfg, db)
    run(e.on_key_results([pat(days=-1)]))
    assert db.one("SELECT COUNT(*) n FROM keys")["n"] == 0
    assert db.one("SELECT COUNT(*) n FROM incidents")["n"] == 0 and e.writes_paused() is None


def test_keys_enforce_pauses_after_switching_from_observe(cfg, db):
    e = Engine(cfg, db)
    run(e.on_key_results([pat(days=-1)]))
    assert e.writes_paused() is None
    db.set("mode:keys", "enforce")
    run(e.on_key_results([pat(days=-1)]))                 # same level as before, still applied in enforce
    assert e.writes_paused() == "GitHub token expired"
    run(e.on_key_results([pat(days=60)]))
    assert e.writes_paused() is None
    assert [r["decision"] for r in db.all("SELECT decision FROM actions WHERE mode='enforce' ORDER BY id")] == \
        ["pause_github_writes", "resume_github_writes"]
    assert db.verify_audit_chain()


def test_token_pause_leaves_operator_pause_alone(cfg, db):
    db.set("mode:keys", "enforce")
    e = Engine(cfg, db)
    e.set_paused("maintenance")
    run(e.on_key_results([pat(days=-1)]))
    assert e.writes_paused() == "maintenance"
    run(e.on_key_results([pat(days=60)]))
    assert e.writes_paused() == "maintenance"
