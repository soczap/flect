import subprocess

import pytest

from flect.actuators.git import Git, IdentityError

NAME, EMAIL = "soczap", "67731207+soczap@users.noreply.github.com"


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    (tmp_path / "f.txt").write_text("x")
    return Git(str(tmp_path), NAME, EMAIL)


def test_commit_is_authored_by_soczap(repo):
    repo.commit_all("first")
    an, ae, cn, ce, body = repo.tip_author()
    assert (an, ae, cn, ce) == (NAME, EMAIL, NAME, EMAIL)
    repo.assert_tip_is_soczap()


def test_refuses_ai_trailer_in_message(repo):
    with pytest.raises(IdentityError):
        repo.commit_all("fix\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
    with pytest.raises(IdentityError):
        repo.commit_all("fix\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)")


def test_push_refused_when_tip_is_not_soczap(repo, tmp_path):
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=someone", "-c", "user.email=x@y.z",
                    "commit", "-qm", "foreign", "--allow-empty"], check=True)
    with pytest.raises(IdentityError):
        repo.push("main:main")
