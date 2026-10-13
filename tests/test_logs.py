import json

from flect.sources.logs import FileFollower, LogTailer, parse_line


def test_parse_access_line():
    line = json.dumps({"ts": "T", "level": "INFO", "logger": "uvicorn.access",
                       "msg": '203.0.113.5:4411 - "POST /api/auth/login?x=1 HTTP/1.1" 401'})
    rec = parse_line(line, "f")
    assert (rec.kind, rec.ip, rec.method, rec.path, rec.status) == ("access", "203.0.113.5", "POST", "/api/auth/login", 401)


def test_parse_ipv6_access_line():
    line = json.dumps({"logger": "uvicorn.access", "msg": '[2001:db8::7]:4411 - "GET / HTTP/1.1" 200'})
    assert parse_line(line, "f").ip == "2001:db8::7"


def test_follow_rotation_and_truncation(tmp_path):
    p = tmp_path / "a.log"
    p.write_text("old\n")
    f = FileFollower(str(p))
    assert f.read_new() == []                    # starts at end
    with p.open("a") as fh:
        fh.write("one\ntwo\npart")
    assert f.read_new() == ["one", "two"]
    with p.open("a") as fh:
        fh.write("ial\n")
    assert f.read_new() == ["partial"]
    p.write_text("x\n")                           # truncated (smaller)
    assert f.read_new() == ["x"]
    p.rename(tmp_path / "a.log.1")                # rotated
    p.write_text("new\n")
    assert f.read_new() == ["new"]


def test_raw_traceback_grouped(tmp_path, db):
    p = tmp_path / "service.out"
    p.write_text("")
    t = LogTailer(db, [str(p)])
    got = []
    t.subscribe(got.append)
    t.poll_once()
    with p.open("a") as fh:
        fh.write('Traceback (most recent call last):\n  File "/x/vigil/a.py", line 1, in f\nValueError: bad\n')
        fh.write(json.dumps({"level": "INFO", "logger": "vigil", "msg": "started"}) + "\n")
    t.poll_once()
    assert got[0].kind == "raw" and "ValueError: bad" in got[0].msg
    assert got[1].kind == "app"
