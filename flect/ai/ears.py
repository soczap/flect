"""Speech to text on this machine, so the operator's voice never leaves the network.

The browser records a short clip and posts it to /api/ai/transcribe. ffmpeg turns it into 16 kHz mono WAV and
whisper.cpp (CPU only, so it never competes with DeepSeek for the GPU) writes the text. One clip at a time.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/mp4", "audio/wav", "audio/x-wav", "audio/wave"}
MAX_BYTES = 4_000_000

# Words Whisper would otherwise mishear: steers it toward Flect's vocabulary.
PROMPT = ("Flect, VIGIL, FRS backend, DeepSeek, UAT, rollback, restart, incident, unblock, approve, "
          "pull request, GitHub, last known good.")

NON_SPEECH = re.compile(r"\[[^\]]*\]|\([^)]*\)|♪+")
# What Whisper tends to "hear" in silence or noise. Dropped when it is the whole transcript.
HALLUCINATIONS = {"you", "thanks for watching", "thank you for watching", "please subscribe"}


class TranscriptionError(RuntimeError):
    pass


class Ears:
    def __init__(self, cfg, run=subprocess.run):
        ai = cfg["ai"]
        self.bin = Path(ai["whisper_bin"])
        self.model = Path(ai["whisper_model"])
        self.threads = int(ai["whisper_threads"])
        self.max_s = int(ai["max_audio_s"])
        self.work = Path(cfg.data_dir) / "work"
        self.run = run
        self.lock = threading.Lock()

    def status(self) -> str:
        """'local' when transcription works here, otherwise why not."""
        if not (self.bin.is_file() and os.access(self.bin, os.X_OK)):
            return f"whisper.cpp not found at {self.bin}"
        if not self.model.is_file():
            return f"Whisper model not found at {self.model}"
        if not shutil.which("ffmpeg"):
            return "ffmpeg is not installed"
        return "local"

    def transcribe(self, audio: bytes, content_type: str) -> str:
        if content_type not in AUDIO_TYPES:
            raise TranscriptionError(f"unsupported audio type {content_type!r}")
        if not audio or len(audio) > MAX_BYTES:
            raise TranscriptionError("audio clip is empty or too large")
        if self.status() != "local":
            raise TranscriptionError(self.status())
        self.work.mkdir(parents=True, exist_ok=True)
        with self.lock, tempfile.TemporaryDirectory(prefix="flect-ears-", dir=self.work) as tmp:
            src, wav = Path(tmp) / "clip", Path(tmp) / "clip.wav"
            src.write_bytes(audio)
            self._call(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(src),
                        "-t", str(self.max_s), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)], 30, "ffmpeg")
            out = self._call([str(self.bin), "-m", str(self.model), "-f", str(wav), "-l", "en",
                              "-t", str(self.threads), "-nt", "-np", "-sns", "-ac", str(audio_ctx(wav)),
                              "--prompt", PROMPT], 90, "whisper")
        return clean(out)

    def _call(self, argv: list[str], timeout: int, what: str) -> str:
        try:
            res = self.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise TranscriptionError(f"{what} took longer than {timeout}s") from None
        if res.returncode != 0:
            raise TranscriptionError(f"{what} failed: {(res.stderr or '').strip()[-300:]}")
        return res.stdout or ""


def audio_ctx(wav: Path) -> int:
    """Whisper encodes a fixed 30 s window; size it to the clip instead. A 3 s command then takes ~0.8 s, not ~2.6 s,
    with the same text (measured on the Spark, small.en, 8 threads)."""
    try:
        seconds = max(0, wav.stat().st_size - 44) / (16000 * 2)
    except OSError:
        return 1500
    return min(1500, math.ceil(seconds / 30 * 1500) + 128)


def clean(text: str) -> str:
    text = NON_SPEECH.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if re.sub(r"[^a-z ]", "", text.lower()).strip() in HALLUCINATIONS:
        return ""
    return text
