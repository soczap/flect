import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flect import config as config_mod  # noqa: E402
from flect.db import DB  # noqa: E402


@pytest.fixture
def cfg(tmp_path):
    c = config_mod.load(path=tmp_path / "none.toml", env={"FLECT_DATA_DIR": str(tmp_path / "data")})
    c.data_dir.mkdir(parents=True, exist_ok=True)
    return c


@pytest.fixture
def db():
    return DB(":memory:")


class FakeClient:
    """Stands in for the llama-server client; returns scripted JSON contents."""

    def __init__(self, responses, healthy=True):
        self.responses = list(responses)
        self.healthy = healthy
        self.calls = []

    def health(self, timeout=5):
        return self.healthy

    def chat(self, messages, schema, name, max_tokens, timeout):
        self.calls.append({"messages": messages, "schema": schema, "name": name})
        content = self.responses.pop(0) if self.responses else "{}"
        if not isinstance(content, str):
            content = json.dumps(content)
        return {"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


@pytest.fixture
def fake_client():
    return FakeClient
