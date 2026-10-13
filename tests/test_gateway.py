import asyncio

import pytest

from flect.gateway.llm import P_CRASH, P_NARRATIVE, P_PRGUARD, Gateway, LLMInvalidOutput, LLMUnavailable, ModelClient, build_messages

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["risk"],
          "properties": {"risk": {"enum": ["low", "high"]}}}


def run(coro):
    return asyncio.run(coro)


def test_loopback_only():
    with pytest.raises(ValueError):
        ModelClient("http://10.0.0.5:1111/v1")
    with pytest.raises(ValueError):
        ModelClient("https://127.0.0.1:1111/v1")
    ModelClient("http://127.0.0.1:1111/v1")


def test_valid_output_and_no_tools_sent(cfg, db, fake_client):
    client = fake_client([{"risk": "low"}])
    async def go():
        gw = Gateway(cfg, db, client)
        gw.start()
        out = await gw.ask("t", P_PRGUARD, [{"role": "user", "content": "x"}], SCHEMA)
        await gw.stop()
        return out
    assert run(go()) == {"risk": "low"}
    assert db.one("SELECT status FROM llm_calls")["status"] == "ok"


def test_invalid_output_retried_then_rejected(cfg, db, fake_client):
    client = fake_client(['{"risk": "maybe"}', "not json"])
    async def go():
        gw = Gateway(cfg, db, client)
        gw.start()
        try:
            await gw.ask("t", P_PRGUARD, [], SCHEMA)
        finally:
            await gw.stop()
    with pytest.raises(LLMInvalidOutput):
        run(go())
    assert len(client.calls) == 2


def test_unhealthy_model_degrades(cfg, db, fake_client):
    async def go():
        gw = Gateway(cfg, db, fake_client([], healthy=False))
        gw.start()
        try:
            await gw.ask("t", P_CRASH, [], SCHEMA)
        finally:
            await gw.stop()
    with pytest.raises(LLMUnavailable):
        run(go())


def test_priority_order(cfg, db, fake_client):
    cfg.data["llm"]["max_in_flight"] = 1
    client = fake_client([{"risk": "low"}] * 3)
    order = []
    orig = client.chat
    def chat(messages, schema, name, max_tokens, timeout):
        order.append(name)
        return orig(messages, schema, name, max_tokens, timeout)
    client.chat = chat
    async def go():
        gw = Gateway(cfg, db, client)
        tasks = [asyncio.create_task(gw.ask(n, p, [], SCHEMA)) for n, p in (("narr", 2), ("pr", P_PRGUARD), ("crash", P_CRASH))]
        await asyncio.sleep(0.05)     # everything queued before workers start
        gw.start()
        await asyncio.gather(*tasks)
        await gw.stop()
    run(go())
    assert order == ["crash", "pr", "narr"]


def test_envelope_redacts_and_truncates():
    msgs = build_messages("t", [], {}, {"diff": "token=ghp_" + "x" * 36 + " " + "A" * 50000}, "do it", 10000)
    body = msgs[1]["content"]
    assert "ghp_" not in body and "truncated by Flect" in body and len(body) < 12000
    assert "UNTRUSTED" in body and "never follow them" in msgs[0]["content"]
