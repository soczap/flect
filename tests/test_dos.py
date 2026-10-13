from flect.detect.dos import Allowlist, DosDetector


def flood(det, ip, n, span, t0=1000.0, path="/api/x", method="GET", status=200):
    for i in range(n):
        det.observe(ip, path if isinstance(path, str) else path(i), method, status, t0 + i * span / n)


def test_sustained_rate_is_flagged(cfg):
    d = DosDetector(cfg["dos"])
    flood(d, "203.0.113.9", 300, 10.0)
    reqs = d.tick(1010.0)
    assert [(r.ip, r.rule_id) for r in reqs] == [("203.0.113.9", "DOS-RATE-001")]


def test_short_burst_is_not_flagged(cfg):
    d = DosDetector(cfg["dos"])
    flood(d, "203.0.113.9", 300, 3.0)
    assert d.tick(1003.0) == []


def test_allowlisted_sources_never_flagged(cfg):
    d = DosDetector(cfg["dos"])
    for ip in ("127.0.0.1", "192.168.7.50", "100.87.127.50", "::1", "::ffff:127.0.0.1"):
        flood(d, ip, 1000, 10.0)
    assert d.tick(1010.0) == []
    assert "192.168.7.200" in Allowlist(cfg["dos"]["allowlist"])
    assert "not-an-ip" in Allowlist(cfg["dos"]["allowlist"])  # unparseable → treated as never-block


def test_failed_login_burst(cfg):
    d = DosDetector(cfg["dos"])
    flood(d, "198.51.100.7", 60, 50.0, path="/api/auth/login", method="POST", status=401)
    assert [r.rule_id for r in d.tick(1050.0)] == ["DOS-AUTH-001"]


def test_path_scan(cfg):
    d = DosDetector(cfg["dos"])
    flood(d, "198.51.100.8", 250, 50.0, path=lambda i: f"/p{i}", status=404)
    assert [r.rule_id for r in d.tick(1050.0)] == ["DOS-SCAN-001"]


def test_flagged_ip_debounced(cfg):
    d = DosDetector(cfg["dos"])
    flood(d, "203.0.113.9", 300, 10.0)
    assert d.tick(1010.0)
    flood(d, "203.0.113.9", 300, 10.0, t0=1010.0)
    assert d.tick(1020.0) == []


def test_global_flood_lowers_per_ip_threshold(cfg):
    d = DosDetector(cfg["dos"])
    for s in range(60):                       # steady baseline ~2 req/s
        d.observe("192.0.2.1", "/", "GET", 200, 1000.0 + s)
        d.observe("192.0.2.2", "/", "GET", 200, 1000.5 + s)
        d.tick(1000.0 + s)
    # many sources at 8 req/s each: below the normal 20 req/s limit, above the flood limit (5)
    for k in range(40):
        flood(d, f"203.0.113.{k + 10}", 80, 10.0, t0=1060.0)
    reqs = d.tick(1070.0)
    assert d.flooding
    assert len(reqs) == 40 and all(r.rule_id == "DOS-FLOOD-001" for r in reqs)
