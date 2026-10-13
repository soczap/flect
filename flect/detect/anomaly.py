"""Log anomaly detection that does not trigger blocks: error-rate and 5xx spikes, new error signatures.

Per-minute counters with an EWMA baseline. A spike is reported when the current minute exceeds
max(min_count, factor x baseline). New exception signatures are reported the first time they are seen.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Anomaly:
    kind: str           # error_spike | http5xx_spike | new_error_signature
    severity: str
    detail: str
    evidence: dict


class AnomalyDetector:
    def __init__(self, factor: float = 4.0, min_count: int = 20, alpha: float = 0.1):
        self.factor, self.min_count, self.alpha = factor, min_count, alpha
        self.minute: int | None = None
        self.counts = {"errors": 0, "http5xx": 0, "requests": 0}
        self.baseline = {"errors": None, "http5xx": None, "requests": None}
        self.signatures: set[str] = set()
        self.warmed = False

    def observe_access(self, status: int, t: float) -> list[Anomaly]:
        out = self._roll(t)
        self.counts["requests"] += 1
        if status >= 500:
            self.counts["http5xx"] += 1
        return out

    def observe_error(self, t: float, signature: str | None = None, exc_type: str | None = None) -> list[Anomaly]:
        out = self._roll(t)
        self.counts["errors"] += 1
        if signature and signature not in self.signatures:
            self.signatures.add(signature)
            if self.warmed:
                out.append(Anomaly("new_error_signature", "medium", f"first occurrence of {exc_type or 'an error'}",
                                   {"signature": signature, "exception": exc_type}))
        return out

    def _roll(self, t: float) -> list[Anomaly]:
        minute = int(t // 60)
        if self.minute is None:
            self.minute = minute
            return []
        if minute == self.minute:
            return []
        out = []
        for key, kind in (("errors", "error_spike"), ("http5xx", "http5xx_spike")):
            count, base = self.counts[key], self.baseline[key]
            if base is not None and count >= self.min_count and count > self.factor * max(base, 1.0):
                out.append(Anomaly(kind, "high", f"{count} {key} in one minute (baseline {base:.1f}/min)",
                                   {"count": count, "baseline": round(base, 2), "minute": self.minute}))
            # Spikes do not move the baseline much, so an attack cannot normalise itself.
            weight = self.alpha / 10 if out else self.alpha
            self.baseline[key] = count if base is None else (1 - weight) * base + weight * count
        r = self.counts["requests"]
        self.baseline["requests"] = r if self.baseline["requests"] is None else 0.9 * self.baseline["requests"] + 0.1 * r
        self.counts = {"errors": 0, "http5xx": 0, "requests": 0}
        self.minute = minute
        self.warmed = True
        return out
