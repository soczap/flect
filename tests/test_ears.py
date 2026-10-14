"""Voice input: audio is transcribed on this machine; the endpoint is token-guarded and bounded."""
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from flect.ai.ears import Ears, TranscriptionError, clean
from flect.server import build_app


def make_ears(cfg, tmp_path, stdout=" Restart  VIGIL please. [BLANK_AUDIO]\n", fail=None):
    binary, model = tmp_path / "whisper-cli", tmp_path / "model.bin"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    model.write_bytes(b"x")
    cfg.data["ai"].update(whisper_bin=str(binary), whisper_model=str(model))
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        if fail == argv[0].rsplit("/", 1)[-1]:
            return subprocess.CompletedProcess(argv, 1, "", "boom")
        return subprocess.CompletedProcess(argv, 0, stdout if argv[0] == str(binary) else "", "")

    return Ears(cfg, run=run), calls


def test_transcribe_converts_then_runs_whisper_on_cpu(cfg, tmp_path):
    ears, calls = make_ears(cfg, tmp_path)
    assert ears.status() == "local"
    assert ears.transcribe(b"webm-bytes", "audio/webm") == "Restart VIGIL please."
    ffmpeg, whisper = calls
    assert ffmpeg[0] == "ffmpeg" and ffmpeg[ffmpeg.index("-ar") + 1] == "16000" and "-t" in ffmpeg
    assert whisper[whisper.index("-l") + 1] == "en" and "-nt" in whisper and "--prompt" in whisper
    assert whisper[whisper.index("-ac") + 1] == "1500"        # wav was not written by the fake ffmpeg
    assert not any(p.name.startswith("flect-ears-") for p in (cfg.data_dir / "work").iterdir())   # temp files gone


def test_rejects_bad_input_and_reports_failures(cfg, tmp_path):
    ears, _ = make_ears(cfg, tmp_path, fail="whisper-cli")
    with pytest.raises(TranscriptionError, match="unsupported"):
        ears.transcribe(b"x", "text/plain")
    with pytest.raises(TranscriptionError, match="empty or too large"):
        ears.transcribe(b"", "audio/webm")
    with pytest.raises(TranscriptionError, match="whisper failed"):
        ears.transcribe(b"x", "audio/webm")
    cfg.data["ai"]["whisper_model"] = str(tmp_path / "missing.bin")
    assert "model not found" in Ears(cfg).status()


def test_audio_ctx_fits_the_clip(tmp_path):
    from flect.ai.ears import audio_ctx
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"\0" * (44 + 16000 * 2 * 3))          # 3 s of 16 kHz mono
    assert audio_ctx(wav) == 278
    wav.write_bytes(b"\0" * (44 + 16000 * 2 * 40))
    assert audio_ctx(wav) == 1500


def test_clean_drops_non_speech_and_silence_hallucinations():
    assert clean("(wind blowing) Fix those issues ♪") == "Fix those issues"
    assert clean(" Thanks for watching!") == ""
    assert clean("you") == ""
    assert clean("yes") == "yes"


def test_transcribe_endpoint(cfg, db, tmp_path):
    ears, _ = make_ears(cfg, tmp_path, stdout=" Yes, go ahead.\n")
    live = SimpleNamespace(ears=ears)
    c = TestClient(build_app(db, cfg, None, live=live), base_url="http://127.0.0.1:1113")
    session = c.get("/api/ai/session").json()
    assert session["ears"] == "local"
    auth = {"x-flect-token": session["token"]}
    assert c.post("/api/ai/transcribe", content=b"a", headers={"content-type": "audio/webm"}).status_code == 403
    r = c.post("/api/ai/transcribe", content=b"audio", headers={**auth, "content-type": "audio/webm;codecs=opus"})
    assert r.status_code == 200 and r.json() == {"text": "Yes, go ahead."}
    assert c.post("/api/ai/transcribe", content=b"a", headers={**auth, "content-type": "text/plain"}).status_code == 415
    big = b"a" * 4_000_001
    assert c.post("/api/ai/transcribe", content=big, headers={**auth, "content-type": "audio/webm"}).status_code == 413
