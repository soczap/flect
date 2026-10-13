"""Poll GitHub (the box is not reachable by webhooks). Uses ETags so unchanged polls cost no rate limit."""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
from dataclasses import dataclass


@dataclass
class PullRequest:
    number: int
    title: str
    body: str
    head_sha: str
    head_ref: str
    head_repo: str | None
    base_ref: str
    author: str
    draft: bool

    @property
    def kind(self) -> str:
        if self.head_ref.startswith("flect/hotfix-"):
            return "hotfix"
        if self.base_ref == "main" and self.head_ref == "uat":
            return "release"
        if self.base_ref == "uat" and self.head_ref == "main":
            return "backmerge"
        return "feature"


def _gh_api(path: str, etag: str | None) -> tuple[int, str | None, str]:
    args = ["gh", "api", "-i", path]
    if etag:
        args += ["-H", f"If-None-Match: {etag}"]
    res = subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)
    out = res.stdout
    sep = "\r\n\r\n" if "\r\n\r\n" in out else "\n\n"
    head, _, body = out.partition(sep)
    status = re.search(r"HTTP/\S+\s+(\d{3})", head)
    new_etag = re.search(r'(?im)^etag:\s*(\S+)', head)
    return (int(status.group(1)) if status else 0), (new_etag.group(1) if new_etag else None), body


def parse_pulls(body: str) -> list[PullRequest]:
    out = []
    for p in json.loads(body or "[]"):
        out.append(PullRequest(
            number=p["number"], title=p.get("title") or "", body=p.get("body") or "",
            head_sha=p["head"]["sha"], head_ref=p["head"]["ref"],
            head_repo=(p["head"].get("repo") or {}).get("full_name"),
            base_ref=p["base"]["ref"], author=(p.get("user") or {}).get("login", ""), draft=bool(p.get("draft"))))
    return out


def approval_from_comments(comments: list[dict], approvers: set[str]) -> str | None:
    """Return the approver's login if a comment *starts with* `/flect approve`. Flect's own comments (also
    posted as soczap) always start with a heading, so model-influenced text can never trigger this."""
    for c in comments:
        text = (c.get("body") or "").strip()
        login = (c.get("user") or {}).get("login")
        if text.lower().startswith("/flect approve") and login in approvers \
                and c.get("author_association") in ("OWNER", "MEMBER", "COLLABORATOR"):
            return login
    return None


class GitHubPoller:
    def __init__(self, db, repo: str, interval: float, on_pr, on_branch_move=None, on_approve=None,
                 approvers: list[str] | None = None):
        self.db = db
        self.repo = repo
        self.interval = interval
        self.on_pr = on_pr                  # async callback(PullRequest)
        self.on_branch_move = on_branch_move  # async callback(branch, old_sha, new_sha)
        self.on_approve = on_approve          # async callback(PullRequest, login)
        self.approvers = set(approvers or [])
        self.last_error: str | None = None
        self.last_ok: float | None = None

    async def poll_once(self) -> None:
        etag = self.db.get("gh:etag:pulls")
        status, new_etag, body = await asyncio.to_thread(
            _gh_api, f"/repos/{self.repo}/pulls?state=open&per_page=50", etag)
        if status == 200:
            self.db.set("gh:etag:pulls", new_etag)
            self.db.set("gh:pulls", [p.__dict__ for p in parse_pulls(body)])
        elif status not in (304,):
            self.last_error = f"pulls poll HTTP {status}"
            return
        for raw in self.db.get("gh:pulls", []):
            pr = PullRequest(**raw)
            seen = self.db.one("SELECT state FROM prs WHERE repo=? AND number=? AND head_sha=?",
                               (self.repo, pr.number, pr.head_sha))
            if not seen and not pr.draft:
                await self.on_pr(pr)
        if self.on_approve:
            await self.check_approvals()
        if self.on_branch_move:
            for branch in ("main", "uat"):
                st, _, b = await asyncio.to_thread(_gh_api, f"/repos/{self.repo}/branches/{branch}", None)
                if st != 200:
                    continue
                sha = json.loads(b)["commit"]["sha"]
                old = self.db.get(f"gh:head:{branch}")
                if old != sha:
                    self.db.set(f"gh:head:{branch}", sha)
                    if old:
                        await self.on_branch_move(branch, old, sha)
        self.last_error = None
        import time
        self.last_ok = time.time()

    async def check_approvals(self) -> None:
        """A needs-human verdict can be overridden by an approver commenting `/flect approve` on the PR."""
        for raw in self.db.get("gh:pulls", []):
            pr = PullRequest(**raw)
            row = self.db.one("SELECT state, updated_ts FROM prs WHERE repo=? AND number=? AND head_sha=?",
                              (self.repo, pr.number, pr.head_sha))
            if not row or row["state"] != "needs_human":
                continue
            st, _, body = await asyncio.to_thread(
                _gh_api, f"/repos/{self.repo}/issues/{pr.number}/comments?since={row['updated_ts'].replace('+00:00', 'Z')}&per_page=50", None)
            if st != 200:
                continue
            login = approval_from_comments(json.loads(body or "[]"), self.approvers)
            if login:
                await self.on_approve(pr, login)

    async def run(self) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"{type(exc).__name__}: {exc}"[:300]
            await asyncio.sleep(self.interval)
