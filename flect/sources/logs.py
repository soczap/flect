"""Follow VIGIL's log files and turn lines into structured records.

Handles rotation (inode change) and truncation (size shrink). Lines are JSON
(`{"ts","level","logger","msg", "exc"?}`); anything else (e.g. a raw traceback printed
before logging is configured) is grouped into `raw` records.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ACCESS_RE = re.compile(
    r'^\[?(?P<ip>[0-9A-Fa-f:.]+?)\]?:(?P<port>\d+) - "(?P<method>[A-Z]+) (?P<path>\S+)[^"]*" (?P<status>\d{3})')
MAX_LINE = 64 * 1024
REPLAY_LIMIT = 256 * 1024     # bytes; larger files are never replayed from offset 0


@dataclass
class Record:
    kind: str                     # access | app | raw
    file: str
    ts: str | None = None
    level: str | None = None
    logger: str | None = None
    msg: str = ""
    exc: str | None = None
    ip: str | None = None
    method: str | None = None
    path: str | None = None
    status: int | None = None
    extra: dict = field(default_factory=dict)


def parse_line(line: str, file: str) -> Record:
    line = line.rstrip("\n")[:MAX_LINE]
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        obj = None
    if not isinstance(obj, dict):
        return Record(kind="raw", file=file, msg=line)
    msg = str(obj.get("msg", ""))
    rec = Record(kind="app", file=file, ts=obj.get("ts"), level=obj.get("level"),
                 logger=obj.get("logger"), msg=msg, exc=obj.get("exc"))
    if rec.logger == "uvicorn.access":
        m = ACCESS_RE.match(msg)
        if m:
            rec.kind = "access"
            rec.ip, rec.method, rec.path = m["ip"], m["method"], m["path"].split("?", 1)[0]
            rec.status = int(m["status"])
    return rec


class FileFollower:
    """Incremental reader with persisted (inode, offset) cursor."""

    def __init__(self, path: str, cursor: dict | None = None, start_at_end: bool = True):
        self.path = Path(path)
        self.inode = (cursor or {}).get("inode")
        self.offset = (cursor or {}).get("offset")
        self.start_at_end = start_at_end
        self._partial = ""

    def _restart_offset(self, size: int) -> int:
        """A fresh/rotated/truncated file is read from the start only while it is small. A large file whose
        size moved backwards (e.g. an unclean shutdown dropped unflushed data) is resumed at the end, so old
        history is never replayed as if it were live traffic."""
        return 0 if size <= REPLAY_LIMIT else size

    def cursor(self) -> dict:
        return {"inode": self.inode, "offset": self.offset}

    def read_new(self, max_bytes: int = 4 * 1024 * 1024) -> list[str]:
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            return []
        if self.inode != st.st_ino:                 # first run or rotated
            first_run = self.inode is None and self.offset is None
            self.inode = st.st_ino
            if first_run and self.start_at_end:
                self.offset = st.st_size
            else:
                self.offset = self._restart_offset(st.st_size)
            self._partial = ""
        if self.offset is None or st.st_size < self.offset:   # truncated, or data lost in an unclean shutdown
            self.offset = self._restart_offset(st.st_size)
            self._partial = ""
        if st.st_size == self.offset:
            return []
        with open(self.path, "rb") as fh:
            fh.seek(self.offset)
            chunk = fh.read(max_bytes)
        self.offset += len(chunk)
        text = self._partial + chunk.decode("utf-8", errors="replace")
        lines = text.split("\n")
        self._partial = lines.pop()  # incomplete trailing line
        if len(self._partial) > MAX_LINE:
            self._partial = ""
        return lines


class LogTailer:
    """Polls all configured files and dispatches records to subscribers."""

    def __init__(self, db, paths: list[str], interval: float = 0.25):
        self.db = db
        self.interval = interval
        self.followers = {p: FileFollower(p, db.get(f"logcursor:{p}")) for p in paths}
        self.subscribers = []
        self.lines_seen = 0
        self._raw_block: dict[str, list[str]] = {}

    def subscribe(self, fn) -> None:
        self.subscribers.append(fn)

    def poll_once(self) -> int:
        count = 0
        for path, follower in self.followers.items():
            before = follower.cursor()
            for line in follower.read_new():
                if not line.strip():
                    continue
                count += 1
                rec = parse_line(line, path)
                if rec.kind == "raw":
                    # Group consecutive raw lines (tracebacks) into one record.
                    block = self._raw_block.setdefault(path, [])
                    block.append(rec.msg)
                    if len(block) < 400:
                        continue
                    rec = Record(kind="raw", file=path, msg="\n".join(block))
                    self._raw_block[path] = []
                else:
                    self._flush_raw(path)
                for fn in self.subscribers:
                    fn(rec)
            self._flush_raw(path)
            if follower.cursor() != before:
                self.db.set(f"logcursor:{path}", follower.cursor())
        self.lines_seen += count
        return count

    def _flush_raw(self, path: str) -> None:
        block = self._raw_block.get(path)
        if block:
            rec = Record(kind="raw", file=path, msg="\n".join(block))
            self._raw_block[path] = []
            for fn in self.subscribers:
                fn(rec)

    async def run(self) -> None:
        # Runs on the event loop (local reads are fast) so subscribers never race with other loop tasks.
        while True:
            self.poll_once()
            await asyncio.sleep(self.interval)
