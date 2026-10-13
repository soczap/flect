import subprocess

from flect.analyze import prguard
from flect.analyze.prguard import Finding, decide, new_findings
from flect.sources.github import PullRequest


def F(rule, sev="medium", file="a.py"):
    return Finding(f"{rule}:{file}", rule, sev, "t", file, 1)


def test_new_findings_counts_per_rule_and_file():
    base = [{"rule_id": "PY-EXEC", "severity": "high", "title": "t", "location": {"path": "a.py", "line": 3}}]
    head = base + [{"rule_id": "PY-EXEC", "severity": "high", "title": "t", "location": {"path": "a.py", "line": 9}},
                   {"rule_id": "PY-EVAL", "severity": "high", "title": "t", "location": {"path": "b.py", "line": 1}}]
    got = sorted((f.rule_id, f.file) for f in new_findings(base, head))
    assert got == [("PY-EVAL", "b.py"), ("PY-EXEC", "a.py")]


def test_existing_findings_do_not_block():
    base = [{"rule_id": "PY-EXEC", "severity": "high", "title": "t", "location": {"path": "a.py", "line": 3}}]
    assert new_findings(base, base) == []


def test_decide_blocks_high_and_secrets():
    assert decide([F("PY-EXEC", "high")], None)[0] == "block"
    d, risk, _ = decide([F("SECRET-MATERIAL", "medium")], None)
    assert d == "block" and risk == "critical"


def test_decide_sensitive_paths_need_human():
    d, _, reasons = decide([F("PG-PATH-001")], None)
    assert d == "needs_human" and "sensitive" in reasons[0]


def test_llm_can_raise_but_not_clear():
    clean_llm = {"risk": "low", "intent_summary": "", "cited_finding_ids": [], "concerns": [], "injection_attempt": False}
    assert decide([F("PY-EXEC", "high")], clean_llm)[0] == "block"           # cannot clear
    worried = dict(clean_llm, risk="high")
    assert decide([], worried)[0] == "needs_human"                           # can raise
    injected = dict(clean_llm, injection_attempt=True)
    assert decide([], injected)[0] == "block"


def test_clean_change_passes():
    assert decide([], None)[0] == "pass"


def test_render_comment_contains_table():
    pr = PullRequest(7, "t", "b", "a" * 40, "feature/x", "soczap/Computer_Vision", "uat", "dev", False)
    v = prguard.Verdict("block", "high", [F("PY-EXEC", "high")], ["new high-severity findings"], None, "not_run")
    md = prguard.render_comment(pr, v, "enforce")
    assert "PY-EXEC" in md and "block" in md


def test_pr_kind_classification():
    mk = lambda head, base: PullRequest(1, "", "", "s", head, None, base, "u", False).kind
    assert mk("flect/hotfix-3", "main") == "hotfix"
    assert mk("uat", "main") == "release"
    assert mk("feature/a", "uat") == "feature"
    assert mk("main", "uat") == "backmerge"


def test_end_to_end_on_local_repo(tmp_path):
    """Build a tiny repo, add a commit with a dangerous call, and check the guard flags it (no LLM, no tests)."""
    src = tmp_path / "src"
    src.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(src), *a], check=True, capture_output=True, text=True)
    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@example.com"); run("config", "user.name", "t")
    (src / "app.py").write_text("def ok():\n    return 1\n")
    run("add", "-A"); run("commit", "-qm", "base")
    run("checkout", "-qb", "uat")
    base = run("rev-parse", "HEAD").stdout.strip()
    (src / "app.py").write_text("import os\ndef ok(cmd):\n    os.system(cmd)\n    return 1\n")
    run("commit", "-qam", "change")
    head = run("rev-parse", "HEAD").stdout.strip()
    mirror = str(src / ".git")
    out = tmp_path / "t"
    prguard.export_tree(mirror, base, str(out / "b"))
    prguard.export_tree(mirror, head, str(out / "h"))
    nf = new_findings(prguard._scan(str(out / "b"), "b"), prguard._scan(str(out / "h"), "h"))
    assert any(f.rule_id == "PY-SHELL" for f in nf)
    assert decide(nf, None)[0] == "block"
