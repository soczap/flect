"""Regressions from the 2026-10-14 unclean reboot: replayed history caused a false DoS block,
false crash bursts, and boot-time 'token not working' pauses."""
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from flect.daemon import Flect
from flect.detect.crash import CrashDetector
from flect.detect.dos import DosDetector
from flect.policy.engine import Engine
from flect.sources.keys import KeyStatus
from flect.sources.logs import FileFollower, Record


def test_large_log_that_shrinks_is_not_replayed(tmp_path):
    p = tmp_path / "vigil.log"
    p.write_text("x" * 600_000 + "\n")
    f = FileFollower(str(p))
    f.read_new()                                     # at end
    with p.open("a") as fh:
        fh.write("y" * 100_000 + "\n")
    f.read_new()
    # unclean shutdown: the tail that was never flushed is gone, file is smaller than our cursor
    p.write_text("x" * 600_000 + "\n")
    assert f.read_new() == []                        # resumed at end: history NOT replayed
    with p.open("a") as fh:
        fh.write("live\n")
    assert f.read_new() == ["live"]


def test_small_truncated_log_is_read_from_start(tmp_path):
    p = tmp_path / "a.log"
    p.write_text("a" * 1000 + "\n")
    f = FileFollower(str(p))
    f.read_new()
    p.write_text("fresh\n")                          # logrotate copytruncate
    assert f.read_new() == ["fresh"]


def test_stale_lines_never_reach_detectors():
    old = (datetime.now(timezone.utc) - timedelta(days=19)).isoformat()
    assert Flect._event_time(Record(kind="access", file="f", ts=old)) is None
    fresh = datetime.now(timezone.utc).isoformat()
    assert abs(Flect._event_time(Record(kind="access", file="f", ts=fresh)) - time.time()) < 5
    assert Flect._event_time(Record(kind="raw", file="f")) is not None


def test_replayed_history_does_not_block(cfg, tmp_path):
    log = tmp_path / "vigil.log"
    log.write_text("")
    cfg.data["target"]["logs"] = [str(log)]
    f = Flect(cfg)
    f.tailer.poll_once()
    base = datetime(2026, 9, 25, 22, 36, tzinfo=timezone.utc)
    with log.open("a") as fh:
        for i in range(500):                         # a busy gallery session from weeks ago
            ts = (base + timedelta(seconds=i / 5)).isoformat().replace("+00:00", "Z")
            fh.write(json.dumps({"ts": ts, "logger": "uvicorn.access",
                                 "msg": f'10.121.9.254:5000 - "GET /api/frs/media/alerts/{i}.jpg HTTP/1.1" 200'}) + "\n")
    f.tailer.poll_once()
    assert f.dos.tick(time.time()) == [] and f.stale_skipped == 500


def test_scan_rule_ignores_successful_browsing(cfg):
    d = DosDetector(cfg["dos"])
    for i in range(400):                             # 400 distinct thumbnails, all 200 OK
        d.observe("10.121.9.254", f"/media/{i}.jpg", "GET", 200, 1000 + i * 0.1)
    assert d.tick(1040.0) == []
    for i in range(80):                              # an actual scanner: distinct 404s
        d.observe("198.51.100.9", f"/wp-{i}.php", "GET", 404, 1000 + i * 0.5)
    assert [r.rule_id for r in d.tick(1040.0)] == ["DOS-SCAN-001"]


def test_single_failed_probe_does_not_pause(cfg, db):
    db.set("mode:keys", "enforce")
    e = Engine(cfg, db)
    pat_fail = KeyStatus("github-pat (gh, soczap)", "github_pat", "gh", None, False, "DNS not up")
    asyncio.run(e.on_key_results([pat_fail]))
    assert e.writes_paused() is None
    assert db.one("SELECT COUNT(*) n FROM incidents")["n"] == 0
    asyncio.run(e.on_key_results([pat_fail]))        # still failing two minutes later → real
    assert e.writes_paused()
    ok = KeyStatus("github-pat (gh, soczap)", "github_pat", "gh",
                   datetime.now(timezone.utc) + timedelta(days=60), True)
    asyncio.run(e.on_key_results([ok]))
    assert e.writes_paused() is None


def test_restart_grace_period(cfg):
    d = CrashDetector(cfg["crash"], "/x")
    P = lambda ok, pid, t: d.observe_probe(SimpleNamespace(http_ok=ok, http_status=None, error="refused",
                                                           active_state="active", n_restarts=0, main_pid=pid), t)
    for t in range(0, 85, 5):                        # host just booted, VIGIL loading models
        assert P(False, 111, t) is None
    assert P(True, 111, 90) is None
    for t in (95, 100):
        assert P(False, 111, t) is None
    assert P(False, 111, 105).severity == "S1"       # a real outage after it came up


def test_failing_service_stays_failing_without_duplicate_incidents(cfg, db):
    e = Engine(cfg, db)
    down = KeyStatus("frs-backend", "service", "https://127.0.0.1:8000/", None, False, "SSLEOFError")
    for _ in range(2):
        asyncio.run(e.on_key_results([down]))
    assert db.one("SELECT COUNT(*) n FROM incidents")["n"] == 1
    db.set("keyfail:frs-backend", 0)                    # e.g. counter lost across a code upgrade
    for _ in range(3):
        asyncio.run(e.on_key_results([down]))
    assert db.all("SELECT state FROM incidents") == [{"state": "open"}]


def test_recovery_closes_github_issue(cfg, db, tmp_path):
    from flect.actuators.notify import Notifier

    class GH:
        closed = []
        def open_issue(self, title, body, labels): return 7
        def close_issue(self, number, comment): GH.closed.append(number); return True

    e = Engine(cfg, db, notifier=Notifier(db, tmp_path / "r", GH(), True))
    down = KeyStatus("ollama", "service", "http://127.0.0.1:11434/api/tags", None, False, "refused")
    asyncio.run(e.on_key_results([down])); asyncio.run(e.on_key_results([down]))
    up = KeyStatus("ollama", "service", "http://127.0.0.1:11434/api/tags", None, True, "status 200")
    asyncio.run(e.on_key_results([up]))
    assert GH.closed == [7] and db.one("SELECT state FROM incidents")["state"] == "resolved"
