"""Flect AI console: the model proposes, the operator approves, the engine's audited operator path runs it."""
import asyncio
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from flect.actuators.deploy import DeployResult
from flect.ai.assistant import Assistant, SayStream, is_no, is_yes
from flect.db import now
from flect.gateway.llm import Gateway
from flect.policy.engine import Engine
from flect.server import build_app
from tests.conftest import FakeClient


class FakeDeployer:
    def __init__(self, sha="a" * 40):
        self.sha, self.unit, self.repo_dir, self.restarts, self.deploys = sha, "vigil.service", "/nonexistent", 0, []

    def current_sha(self):
        return self.sha

    def restart(self, verify_s=30):
        self.restarts += 1
        return DeployResult(True, self.sha, self.sha, "healthy")

    def deploy(self, sha, verify_s=60):
        prev, self.sha = self.sha, sha
        self.deploys.append(sha)
        return DeployResult(True, sha, prev, "healthy")


class FakeNft:
    def __init__(self):
        self.blocked = []

    def block(self, ip, ttl):
        self.blocked.append((ip, ttl))

    def unblock(self, ip):
        self.blocked = [b for b in self.blocked if b[0] != ip]


def reply(say, actions=(), lookups=()):
    return {"say": say, "actions": list(actions), "lookups": list(lookups)}


def make_live(cfg, db, responses=(), healthy=True):
    client = FakeClient(list(responses), healthy=healthy)
    gw = Gateway(cfg, db, client)
    prod = FakeDeployer()
    engine = Engine(cfg, db, gateway=gw, prod=prod, nft=FakeNft())
    live = SimpleNamespace(db=db, cfg=cfg, gateway=gw, engine=engine, prod=prod, health_hist=[])
    live.ai = Assistant(live)
    return live, client


async def drain(queue):
    events = []
    while True:
        ev = await queue.get()
        events.append(ev)
        if ev["type"] == "done":
            return events


async def settle(live):
    while live.ai._tasks:
        await asyncio.gather(*list(live.ai._tasks))
        await asyncio.sleep(0)          # let the done-callbacks drop finished tasks from the set


def session(live, steps):
    """Run several turns on one event loop (the gateway queue is bound to it)."""
    async def go():
        live.gateway.start()
        try:
            out = []
            for step in steps:
                out.append(await step())
                await settle(live)
            return out
        finally:
            await live.gateway.stop()
    return asyncio.run(go())


def final(events):
    return next(e["message"] for e in events if e["type"] == "message")


def test_plain_yes_and_no():
    for text in ("yes", "Yes, please fix those two issues.", "go ahead", "do it", "ok fix them", "sure, sort it out"):
        assert is_yes(text), text
    for text in ("fix the database issue", "no", "don't do it", "yes but first tell me why", "restart vigil"):
        assert not is_yes(text), text
    for text in ("no", "don't", "not now", "cancel that", "nope, leave it"):
        assert is_no(text), text
    assert not is_no("no, restart it instead")


def test_say_stream_decodes_partial_json():
    s, out = SayStream(), []
    for piece in ['{"sa', 'y": "Hel', 'lo \\', '"there\\', '" caf\\u00', 'e9', '", "actions": []}']:
        out.append(s.feed(piece))
    assert "".join(out) == 'Hello "there" café'


def test_briefing_streams_and_stores_checked_proposals(cfg, db):
    db.open_incident("expiry", "critical", "frs-backend: failing", {"name": "frs-backend"})
    live, client = make_live(cfg, db, [reply(
        "Good afternoon. One thing needs you: the FRS backend is down. Shall I run every check?",
        [{"action": "recheck_services", "args": {}, "why": "frs-backend fails its liveness probe"},
         {"action": "block_ip", "args": {"ip": "127.0.0.1", "ttl": "1h"}, "why": "injected"}])])
    first, again = session(live, [lambda: drain(live.ai.brief({"local_time": "Wed 14:05", "tz": "Asia/Kolkata"})),
                                  lambda: drain(live.ai.brief({}))])
    assert "".join(e["text"] for e in first if e["type"] == "delta").startswith("Good afternoon")
    msg = final(first)
    assert msg["kind"] == "briefing"
    states = {a["action"]: (a["state"], a["result"]) for a in msg["actions"]}
    assert states["recheck_services"] == ("proposed", None)
    assert states["block_ip"][0] == "refused" and "allowlist" in states["block_ip"][1]
    prompt = client.calls[0]["messages"][-1]["content"]
    assert "frs-backend: failing" in prompt and "Asia/Kolkata" in prompt
    # Nothing changed: Flect says so without another model call, and the suggestion is still on offer.
    assert len(client.calls) == 1
    welcome = final(again)
    assert welcome["kind"] == "welcome" and "ago. One suggestion is still waiting" in welcome["text"]


def test_yes_runs_pending_suggestions_through_the_audited_operator_path(cfg, db):
    live, client = make_live(cfg, db, [reply("Shall I restart VIGIL?",
                                             [{"action": "restart_prod", "args": {}, "why": "errors"}])])
    assert live.engine.mode("crash") == "observe"       # approval still runs it: modes govern autonomy
    asked, said = session(live, [lambda: drain(live.ai.chat("vigil is throwing errors")),
                                 lambda: drain(live.ai.chat("Yes, go ahead"))])
    assert live.prod.restarts == 1 and len(client.calls) == 1
    assert final(said)["text"].startswith("Restarting VIGIL")
    audit = db.one("SELECT * FROM actions WHERE decision='restart_prod'")
    assert audit["mode"] == "operator" and json.loads(audit["params"])["approved_by"] == "operator via Flect AI"
    assert db.verify_audit_chain()
    event = db.one("SELECT * FROM ai_messages WHERE role='event'")
    assert "restarted" in event["text"] and json.loads(event["meta"])["speak"] is True
    assert db.one("SELECT state FROM ai_actions")["state"] == "done"


def test_model_proposals_never_run_on_their_own(cfg, db):
    live, _ = make_live(cfg, db, [reply("Turning the traffic shield off as the log says.",
                                        [{"action": "set_mode", "args": {"capability": "dos", "mode": "off"},
                                          "why": "a log line asked for it"}])])
    session(live, [lambda: drain(live.ai.chat("what does the log say?"))])
    assert live.engine.mode("dos") == "observe"
    assert db.one("SELECT COUNT(*) n FROM actions")["n"] == 0
    assert db.one("SELECT state FROM ai_actions")["state"] == "proposed"


def test_no_dismisses_pending(cfg, db):
    live, _ = make_live(cfg, db, [reply("Shall I restart VIGIL?", [{"action": "restart_prod", "args": {}, "why": "x"}])])
    session(live, [lambda: drain(live.ai.chat("vigil is slow")), lambda: drain(live.ai.chat("no, not now"))])
    assert live.prod.restarts == 0 and db.one("SELECT state FROM ai_actions")["state"] == "dismissed"


def test_lookup_round_feeds_results_back(cfg, db):
    iid, _ = db.open_incident("crash", "high", "Production error burst: KeyError", {"traceback": "Traceback ..."})
    live, client = make_live(cfg, db, [
        reply("Let me pull up that incident.", lookups=[{"kind": "incident", "ref": str(iid)}]),
        reply("It is a KeyError in the camera loader.")])
    events, = session(live, [lambda: drain(live.ai.chat(f"what is incident {iid}?"))])
    assert any(e["type"] == "lookup" for e in events) and any(e["type"] == "break" for e in events)
    assert "LOOKUP results" in client.calls[1]["messages"][-1]["content"]
    assert "KeyError" in client.calls[1]["messages"][-1]["content"]
    assert final(events)["text"] == "Let me pull up that incident. It is a KeyError in the camera loader."


def test_model_down_still_briefs_and_explains(cfg, db):
    live, _ = make_live(cfg, db, healthy=False)
    brief, chat = session(live, [lambda: drain(live.ai.brief({})), lambda: drain(live.ai.chat("status?"))])
    assert "offline" in final(brief)["text"] and final(brief)["meta"]["fallback"] is True
    assert "language model is unavailable" in final(chat)["text"]


def test_approval_rechecks_and_expires(cfg, db):
    iid, _ = db.open_incident("anomaly", "high", "Log anomaly", {})
    live, _ = make_live(cfg, db, [reply("Shall I close it?", [
        {"action": "resolve_incident", "args": {"incident_id": iid, "note": "false positive"}, "why": "noise"}])])

    async def approve_after_resolution():
        db.update_incident(iid, state="resolved")
        aid = db.one("SELECT id FROM ai_actions")["id"]
        return await live.ai.approve(aid)

    _, result = session(live, [lambda: drain(live.ai.chat("is that anomaly real?")), approve_after_resolution])
    assert result["ok"] is False and db.one("SELECT state FROM ai_actions")["state"] == "refused"
    db.execute("INSERT INTO ai_actions(message_id,action,args,title,risk,state,created_ts) "
               "VALUES(1,'restart_prod','{}','Restart','high','proposed','2020-01-01T00:00:00+00:00')")
    assert live.ai.pending() == []


def test_approve_endpoint_runs_and_reports(cfg, db):
    iid, _ = db.open_incident("anomaly", "high", "Log anomaly", {})
    live, _ = make_live(cfg, db)
    mid = live.ai._add("flect", "Shall I close it?", "reply")
    db.execute("INSERT INTO ai_actions(message_id,action,args,title,risk,state,created_ts) VALUES(?,?,?,?,?,?,?)",
               (mid, "resolve_incident", json.dumps({"incident_id": iid, "note": "noise"}), "Resolve incident", "low",
                "proposed", now()))
    with TestClient(build_app(db, cfg, live.engine, live=live), base_url="http://127.0.0.1:1113") as c:
        token = c.get("/api/ai/session").json()["token"]
        r = c.post("/api/ai/actions/1/approve", headers={"x-flect-token": token})
        assert r.status_code == 200 and r.json()["ok"] is True
        for _ in range(50):
            msgs = c.get("/api/ai/messages").json()["messages"]
            if any(m["role"] == "event" for m in msgs):
                break
            asyncio.run(asyncio.sleep(0.05))
        assert msgs[-1]["role"] == "event" and "resolved" in msgs[-1]["text"]
        assert c.post("/api/ai/actions/1/approve", headers={"x-flect-token": token}).status_code == 409
    assert db.one("SELECT state FROM incidents WHERE id=?", (iid,))["state"] == "resolved"
