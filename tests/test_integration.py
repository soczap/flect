"""Daemon wiring without touching production: logs come from a temp file, actuators are fakes."""
import asyncio
import json
import time
from datetime import datetime, timezone

from flect.daemon import Flect


def access_line(ip, t, path="/api/events", status=200):
    ts = datetime.fromtimestamp(t, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return json.dumps({"ts": ts, "level": "INFO", "logger": "uvicorn.access",
                       "msg": f'{ip}:5555 - "GET {path} HTTP/1.1" {status}'}) + "\n"


def test_flood_in_logs_produces_observe_block(cfg, tmp_path):
    log = tmp_path / "vigil.log"
    log.write_text("")
    cfg.data["target"]["logs"] = [str(log)]
    f = Flect(cfg)
    f.tailer.poll_once()                       # establish cursor at end of file
    now_t = time.time()
    with log.open("a") as fh:
        for i in range(300):                    # 30 req/s for 10 s from one external IP
            fh.write(access_line("203.0.113.77", now_t - 10 + i / 30))
        for i in range(50):
            fh.write(access_line("127.0.0.1", now_t - 10 + i / 5, "/api/health"))
    f.tailer.poll_once()

    async def go():
        for req in f.dos.tick(now_t):
            await f.engine.on_block_request(req)
    asyncio.run(go())
    block = f.db.one("SELECT ip, rule_id, mode, active FROM blocks")
    assert block == {"ip": "203.0.113.77", "rule_id": "DOS-RATE-001", "mode": "observe", "active": 0}
    assert f.db.one("SELECT kind FROM incidents")["kind"] == "dos"


def test_traceback_burst_in_logs_raises_crash_event(cfg, tmp_path):
    log = tmp_path / "service.out"
    log.write_text("")
    cfg.data["target"]["logs"] = [str(log)]
    f = Flect(cfg)
    f.tailer.poll_once()
    exc = ("Traceback (most recent call last):\n"
           f'  File "{cfg["target"]["prod_dir"]}/vigil/api/events.py", line 9, in h\n'
           "KeyError: 'camera'")
    with log.open("a") as fh:
        for _ in range(6):
            fh.write(json.dumps({"level": "ERROR", "logger": "vigil", "msg": "boom", "exc": exc}) + "\n")
    f.tailer.poll_once()
    kinds = []
    while not f.pending.empty():
        kinds.append(f.pending.get_nowait()[0])
    assert "crash" in kinds
