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


class GitHubPoller:
    def __init__(self, db, repo: str, interval: float, on_pr, on_branch_move=None):
        self.db = db
        self.repo = repo
        self.interval = interval
        self.on_pr = on_pr                  # async callback(PullRequest)
        self.on_branch_move = on_branch_move  # async callback(branch, old_sha, new_sha)
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

    async def run(self) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"{type(exc).__name__}: {exc}"[:300]
            await asyncio.sleep(self.interval)
