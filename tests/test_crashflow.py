import asyncio
from types import SimpleNamespace

from flect.actuators.deploy import DeployResult
from flect.detect.crash import CrashEvent
from flect.policy.engine import Engine


class FakeDeployer:
    def __init__(self, sha, healthy_after_deploy=True):
        self.sha = sha
        self.unit = "vigil.service"
        self.repo_dir = "/nonexistent"
        self.healthy = healthy_after_deploy
        self.deploys = []
        self.restarts = 0

    def current_sha(self):
        return self.sha

    def deploy(self, sha, verify_s=60):
        prev, self.sha = self.sha, sha
        self.deploys.append(sha)
        return DeployResult(self.healthy, sha, prev, "healthy" if self.healthy else "not healthy")

    def restart(self, verify_s=30):
        self.restarts += 1
        return DeployResult(True, self.sha, self.sha, "healthy")


def s1(classification="unknown"):
    return CrashEvent("S1", "health failed 3 consecutive probes", classification, None, {})


def seed(db, engine, lkg="a" * 40, bad="b" * 40):
    engine.record_deployment("prod", lkg, None, "bootstrap", "healthy")
    db.execute("UPDATE deployments SET state='lkg'")
    engine.record_deployment("prod", bad, lkg, "human_merge", "healthy")


def test_observe_mode_only_records(cfg, db):
    prod = FakeDeployer("b" * 40)
    e = Engine(cfg, db, prod=prod)
    seed(db, e)
    asyncio.run(e.on_crash(s1()))
    assert prod.deploys == [] and prod.restarts == 0
    assert db.one("SELECT decision, mode FROM actions WHERE decision LIKE 'deploy_prod%'") == \
        {"decision": "deploy_prod:rollback", "mode": "observe"}
    assert db.one("SELECT kind, state FROM incidents")["kind"] == "crash"


def test_enforce_rolls_back_to_last_known_good(cfg, db):
    db.set("mode:crash", "enforce")
    prod = FakeDeployer("b" * 40)
    e = Engine(cfg, db, prod=prod)
    seed(db, e)
    asyncio.run(e.on_crash(s1()))
    assert prod.deploys == ["a" * 40]
    inc = db.one("SELECT state, summary FROM incidents")
    assert inc["state"] == "mitigated" and "last-known-good" in inc["summary"]


def test_restart_when_already_on_lkg(cfg, db):
    db.set("mode:crash", "enforce")
    prod = FakeDeployer("a" * 40)
    e = Engine(cfg, db, prod=prod)
    e.record_deployment("prod", "a" * 40, None, "bootstrap", "healthy")
    db.execute("UPDATE deployments SET state='lkg'")
    asyncio.run(e.on_crash(s1()))
    assert prod.deploys == [] and prod.restarts == 1


def test_duplicate_crash_signals_handled_once(cfg, db):
    db.set("mode:crash", "enforce")
    prod = FakeDeployer("b" * 40)
    e = Engine(cfg, db, prod=prod)
    seed(db, e)
    asyncio.run(e.on_crash(s1()))
    asyncio.run(e.on_crash(s1()))
    assert prod.deploys == ["a" * 40]


def test_deploy_budget_stops_loops(cfg, db):
    db.set("mode:crash", "enforce")
    prod = FakeDeployer("b" * 40)
    e = Engine(cfg, db, prod=prod)
    seed(db, e)
    for _ in range(3):
        e.record_deployment("prod", "c" * 40, None, "rollback", "healthy")
    asyncio.run(e.on_crash(s1()))
    assert prod.deploys == []
    assert db.one("SELECT state FROM incidents")["state"] == "needs_human"


def test_environment_crash_does_not_roll_back(cfg, db):
    db.set("mode:crash", "enforce")
    prod = FakeDeployer("b" * 40)
    e = Engine(cfg, db, prod=prod)
    seed(db, e)
    tb = SimpleNamespace(env_marker="disk_full", signature="s", exc_type="OSError", exc_msg="", text="", app_frames=[])
    asyncio.run(e.on_crash(CrashEvent("S1", "down", "environment", tb, {})))
    assert prod.deploys == [] and prod.restarts == 1
    assert db.one("SELECT state FROM incidents")["state"] == "needs_human"


def test_failed_deploy_rolls_back(cfg, db):
    db.set("mode:cicd", "enforce")
    db.set("mode:crash", "enforce")
    prod = FakeDeployer("a" * 40, healthy_after_deploy=False)
    e = Engine(cfg, db, prod=prod)
    e.record_deployment("prod", "a" * 40, None, "bootstrap", "healthy")
    db.execute("UPDATE deployments SET state='lkg'")
    asyncio.run(e.deploy_prod("d" * 40, "human_merge", "cicd"))
    assert prod.deploys == ["d" * 40, "a" * 40]


def s2():
    return CrashEvent("S2", "KeyError repeated 5x in 600s", "unknown", None, {})


def test_error_burst_right_after_a_deploy_rolls_back(cfg, db):
    db.set("mode:crash", "enforce")
    prod = FakeDeployer("b" * 40)
    e = Engine(cfg, db, prod=prod)
    seed(db, e)                                           # "b" was deployed after a human merge, just now
    asyncio.run(e.on_crash(s2()))
    assert prod.deploys == ["a" * 40] and prod.restarts == 0
    inc = db.one("SELECT state, summary FROM incidents")
    assert inc["state"] == "mitigated" and "last-known-good" in inc["summary"]


def test_error_burst_after_the_watch_window_does_not_roll_back(cfg, db):
    db.set("mode:crash", "enforce")
    prod = FakeDeployer("b" * 40)
    e = Engine(cfg, db, prod=prod)
    seed(db, e)
    db.execute("UPDATE deployments SET started_ts=datetime('now','-30 minutes') WHERE sha=?", ("b" * 40,))
    asyncio.run(e.on_crash(s2()))
    assert prod.deploys == [] and prod.restarts == 0
    assert db.one("SELECT state FROM incidents")["state"] == "open"


def test_error_burst_after_a_manual_change_does_not_roll_back(cfg, db):
    db.set("mode:crash", "enforce")
    prod = FakeDeployer("b" * 40)
    e = Engine(cfg, db, prod=prod)
    e.record_deployment("prod", "a" * 40, None, "bootstrap", "healthy")
    db.execute("UPDATE deployments SET state='lkg'")
    e.record_deployment("prod", "b" * 40, "a" * 40, "manual", "healthy")   # changed outside Flect
    asyncio.run(e.on_crash(s2()))
    assert prod.deploys == []


def test_watched_burst_without_rollback_target_reopens(cfg, db):
    db.set("mode:crash", "enforce")
    prod = FakeDeployer("a" * 40)
    e = Engine(cfg, db, prod=prod)
    e.record_deployment("prod", "a" * 40, None, "hotfix", "healthy")
    db.execute("UPDATE deployments SET state='lkg'")
    asyncio.run(e.on_crash(s2()))
    assert prod.deploys == [] and prod.restarts == 0
    inc = db.one("SELECT state, summary FROM incidents")
    assert inc["state"] == "open" and "no older last-known-good" in inc["summary"]
