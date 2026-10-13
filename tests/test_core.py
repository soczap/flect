from flect import redact
from flect.config import load


def test_defaults_are_observe(cfg):
    for cap in ("prguard", "dos", "crash", "cicd", "vapt", "keys"):
        assert cfg.mode(cap) == "observe"


def test_env_override_and_dry_run(tmp_path):
    c = load(path=tmp_path / "x.toml", env={"FLECT_MODE_DOS": "enforce", "FLECT_DATA_DIR": str(tmp_path)})
    assert c.mode("dos") == "enforce"
    c = load(path=tmp_path / "x.toml", env={"FLECT_MODE_DOS": "enforce", "FLECT_DRY_RUN": "1", "FLECT_DATA_DIR": str(tmp_path)})
    assert c.mode("dos") == "observe"


def test_redaction_patterns():
    text = ("token ghp_" + "a" * 36 + " key=" + "s3cretvalue " + "github_pat_" + "b" * 40 +
            " AKIA" + "C" * 16 + " -----BEGIN RSA " + "PRIVATE KEY-----\nabc\n-----END RSA " + "PRIVATE KEY-----")
    out = redact.redact(text)
    for leaked in ("ghp_", "github_pat_", "AKIA", "s3cretvalue", "BEGIN RSA"):
        assert leaked not in out


def test_registered_secret_values_are_removed():
    redact.register_secret("hunter2-very-secret")
    assert "hunter2-very-secret" not in redact.redact("password is hunter2-very-secret ok")


def test_signal_payload_redacted_and_audit_chain(db):
    db.signal("t", "k", "low", None, {"x": "ghp_" + "z" * 36})
    assert "ghp_" not in db.all("SELECT payload FROM signals")[0]["payload"]
    for i in range(5):
        db.record_action("block_ip", f"10.0.0.{i}", {"i": i}, "observe", None, "would_do")
    assert db.verify_audit_chain()
    db.execute("UPDATE actions SET target='tampered' WHERE id=3")
    assert not db.verify_audit_chain()


def test_incident_dedupe(db):
    a, created = db.open_incident("dos", "high", "t", {}, dedupe_key="dos:1.2.3.4")
    b, created2 = db.open_incident("dos", "high", "t", {}, dedupe_key="dos:1.2.3.4")
    assert created and not created2 and a == b
    db.update_incident(a, state="resolved")
    c, created3 = db.open_incident("dos", "high", "t", {}, dedupe_key="dos:1.2.3.4")
    assert created3 and c != a
