from types import SimpleNamespace

from flect.detect.crash import CrashDetector, classify, parse_traceback

APP = "/home/enterprise/VIGIL"
CODE_TB = (
    "Traceback (most recent call last):\n"
    '  File "/home/enterprise/VIGIL/.venv/lib/python3.12/site-packages/starlette/routing.py", line 10, in app\n'
    "    await route()\n"
    '  File "/home/enterprise/VIGIL/vigil/api/events.py", line 88, in list_events\n'
    "    return rows[0]\n"
    "IndexError: list index out of range")
ENV_TB = (
    "Traceback (most recent call last):\n"
    '  File "/home/enterprise/VIGIL/vigil/db.py", line 12, in init_db\n'
    "    conn.execute(sql)\n"
    "OSError: [Errno 28] No space left on device")


def probe(ok=True, state="active", restarts=0):
    return SimpleNamespace(http_ok=ok, http_status=200 if ok else None, error=None if ok else "refused",
                           active_state=state, n_restarts=restarts)


def test_parse_code_traceback():
    tb = parse_traceback(CODE_TB, APP)
    assert tb.exc_type == "IndexError"
    assert [f["rel"] for f in tb.app_frames] == ["vigil/api/events.py"]
    assert classify(tb) == "code"


def test_environment_marker_wins():
    tb = parse_traceback(ENV_TB, APP)
    assert tb.env_marker == "disk_full" and classify(tb) == "environment"


def test_signature_stable_across_line_shifts():
    a = parse_traceback(CODE_TB, APP).signature
    b = parse_traceback(CODE_TB.replace("line 88", "line 91"), APP).signature
    assert a == b


def test_s2_fires_once_at_threshold(cfg):
    d = CrashDetector(cfg["crash"], APP)
    events = [d.observe_traceback(CODE_TB, 1000.0 + i) for i in range(8)]
    fired = [e for e in events if e]
    assert len(fired) == 1 and fired[0].severity == "S2" and fired[0].classification == "code"


def test_s1_on_consecutive_health_failures(cfg):
    d = CrashDetector(cfg["crash"], APP)
    assert d.observe_probe(probe(), 0) is None
    assert d.observe_probe(probe(False), 5) is None
    assert d.observe_probe(probe(False), 10) is None
    ev = d.observe_probe(probe(False), 15)
    assert ev and ev.severity == "S1"
    assert d.observe_probe(probe(False), 20) is None   # one event per outage
    d.observe_probe(probe(), 25)
    assert d.observe_probe(probe(False), 30) is None


def test_s1_on_restart_loop(cfg):
    d = CrashDetector(cfg["crash"], APP)
    d.observe_probe(probe(restarts=4), 0)
    assert d.observe_probe(probe(restarts=5), 5) is None
    ev = d.observe_probe(probe(restarts=6), 10)
    assert ev and "restarts" in ev.reason
