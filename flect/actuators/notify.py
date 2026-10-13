"""Reports to humans: always to the local report store/dashboard; to GitHub issues/comments when enabled."""
from __future__ import annotations

from pathlib import Path

from flect.db import DB, now
from flect.redact import redact


class Notifier:
    def __init__(self, db: DB, reports_dir: Path, github=None, github_enabled: bool = False, paused=None):
        self.db = db
        self.paused = paused or (lambda: None)   # callable → reason string when GitHub writes are paused
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.github = github
        self.github_enabled = github_enabled

    def save_report(self, kind: str, name: str, markdown: str, sha: str | None = None,
                    pr_number: int | None = None, max_severity: str | None = None) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)[:120]
        path = self.reports_dir / f"{kind}-{safe}.md"
        path.write_text(redact(markdown))
        self.db.execute("INSERT INTO reports(kind,ref_sha,pr_number,path,max_severity,created_ts) VALUES(?,?,?,?,?,?)",
                        (kind, sha, pr_number, str(path), max_severity, now()))
        return path

    def incident(self, incident_id: int, title: str, body: str, labels: list[str] | None = None) -> int | None:
        """Record locally; open a GitHub issue (once per incident) when GitHub notifications are enabled."""
        self.save_report("incident", f"{incident_id}", f"# {title}\n\n{body}\n")
        row = self.db.one("SELECT github_issue FROM incidents WHERE id=?", (incident_id,))
        if not (self.github_enabled and self.github) or (row and row["github_issue"]) or self.paused():
            return row["github_issue"] if row else None
        number = self.github.open_issue(f"[flect] {title}", redact(body), ["flect", *(labels or [])])
        if number:
            self.db.update_incident(incident_id, github_issue=number)
        return number

    def pr_comment(self, number: int, body: str) -> bool:
        if not (self.github_enabled and self.github) or self.paused():
            return False
        return self.github.comment(number, redact(body))
