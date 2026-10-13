"""Strip secret material from any text before it leaves the process (LLM, GitHub, logs, UI)."""
from __future__ import annotations

import re
import threading

_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"), "[REDACTED PRIVATE KEY]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b|\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED GITHUB TOKEN]"),
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), "[REDACTED AWS KEY]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "[REDACTED JWT]"),
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{12,}"), r"\1 [REDACTED]"),
    (re.compile(r"(?i)(\b[\w-]*(?:password|passwd|secret|key|token|authorization|credential)s?\s*[=:]\s*)[^\s,;\"']+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(https?://)[^/@\s:]+:[^/@\s]+@"), r"\1[REDACTED]@"),
]

_known_values: set[str] = set()
_lock = threading.Lock()


def register_secret(value: str | None) -> None:
    """Exact values (e.g. read from .env for expiry checks) that must never be emitted."""
    if value and len(value) >= 6:
        with _lock:
            _known_values.add(value)


def redact(text: str, limit: int | None = None) -> str:
    if not isinstance(text, str):
        text = str(text)
    with _lock:
        values = sorted(_known_values, key=len, reverse=True)
    for value in values:
        text = text.replace(value, "[REDACTED]")
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    if limit is not None and len(text) > limit:
        text = text[:limit] + "…[truncated]"
    return text


def redact_obj(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [redact_obj(v) for v in value]
    if isinstance(value, dict):
        return {k: redact_obj(v) for k, v in value.items()}
    return value
