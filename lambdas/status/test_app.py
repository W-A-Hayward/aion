import importlib.util
import json
import os
import uuid
from decimal import Decimal

import pytest

_spec = importlib.util.spec_from_file_location("status_app", os.path.join(os.path.dirname(__file__), "app.py"))
app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(app)


class FakeTable:
    def __init__(self, items):
        self.items = items

    def get_item(self, Key):
        it = self.items.get(Key["jobId"])
        return {"Item": it} if it else {}


JOB = str(uuid.uuid4())
OTHER = str(uuid.uuid4())
LEGACY = str(uuid.uuid4())
TOKEN = "t" * 40
OWNER_HASH = app.owner_of({"headers": {"x-cascade-session": TOKEN}})


@pytest.fixture(autouse=True)
def table(monkeypatch):
    t = FakeTable(
        {
            JOB: {
                "jobId": JOB,
                "status": "DONE",
                "answer": "hi",
                "toolCalls": [],
                "citations": [],
                "durationMs": Decimal("1234"),
                "question": "secret question",
                "sessionId": "s",
                "traceKey": "traces/x.json",
                "ownerHash": OWNER_HASH,
            },
            LEGACY: {"jobId": LEGACY, "status": "DONE", "answer": "no owner"},
        }
    )
    monkeypatch.setattr(app, "_table", lambda: t)


def call(i, token=TOKEN):
    event = {"pathParameters": {"id": i}}
    if token is not None:
        event["headers"] = {"X-Cascade-Session": token}
    return app.lambda_handler(event, None)


def test_done_legacy_answer_string_is_wrapped():
    r = call(JOB)
    assert r["statusCode"] == 200
    body = json.loads(r["body"])
    assert body["status"] == "DONE" and body["answer"]["text"] == "hi" and body["durationMs"] == 1234
    assert body["stage"] == "done" and body["stages"] == [] and body["job_id"] == JOB
    assert "question" not in body and "sessionId" not in body and "traceKey" not in body


def test_full_contract_object(monkeypatch):
    answer = {"verdict": "MYTH", "headline": "h", "text": "t [1]", "refusal": False, "caveat": "c"}
    stages = [{"stage": "queued", "t": "a"}, {"stage": "agent_started", "t": "b"},
              {"stage": "tool:get_portfolio_facts", "t": "c"}, {"stage": "guardrail", "t": "d"},
              {"stage": "done", "t": "e"}]
    item = {"jobId": JOB, "status": "DONE", "ownerHash": OWNER_HASH, "answer": answer, "stages": stages,
            "trace": [{"step": 1, "tool": "get_portfolio_facts", "tag": "measured", "ms": 5}],
            "data": {"risk_share": {"rates": Decimal("0.707")}, "scenario": None},
            "citations": [{"n": 1, "evidence_id": "e1"}], "toolCalls": [{"name": "x"}], "claims": [],
            "traceKey": "traces/x.json", "ownerHashExtra": "no"}
    monkeypatch.setattr(app, "_table", lambda: FakeTable({JOB: item}))
    body = json.loads(call(JOB)["body"])
    assert body["job_id"] == JOB and body["stage"] == "done" and body["stages"] == stages
    assert body["answer"] == answer and body["citations"] == [{"n": 1, "evidence_id": "e1"}]
    assert body["trace"][0]["tag"] == "measured"
    assert body["data"]["risk_share"] == {"rates": 0.707}
    assert set(body["data"]) == {"risk_share", "shields", "cushion", "betas", "twin_series",
                                 "stock_bond_series", "scenario"}
    assert body["toolCalls"] == [{"name": "x"}] and "traceKey" not in body and "ownerHash" not in body


def test_running_job_has_empty_contract(monkeypatch):
    item = {"jobId": JOB, "status": "RUNNING", "ownerHash": OWNER_HASH,
            "stages": [{"stage": "queued", "t": "a"}, {"stage": "agent_started", "t": "b"}]}
    monkeypatch.setattr(app, "_table", lambda: FakeTable({JOB: item}))
    body = json.loads(call(JOB)["body"])
    assert body["stage"] == "agent_started" and body["answer"] is None
    assert body["trace"] == [] and body["citations"] == [] and body["data"]["shields"] == []


def test_failed_job_reports_error(monkeypatch):
    item = {"jobId": JOB, "status": "FAILED", "ownerHash": OWNER_HASH, "error": "boom",
            "stages": [{"stage": "queued", "t": "a"}, {"stage": "failed", "t": "b"}]}
    monkeypatch.setattr(app, "_table", lambda: FakeTable({JOB: item}))
    body = json.loads(call(JOB)["body"])
    assert body["stage"] == "failed" and body["error"] == "boom"


def test_not_found():
    assert call(OTHER)["statusCode"] == 404


@pytest.mark.parametrize("bad", ["abc", "", None, "../x", JOB + "x", JOB.replace("-", "")])
def test_invalid_id(bad):
    assert call(bad)["statusCode"] == 400


def test_missing_path_params():
    assert app.lambda_handler({"headers": {"x-cascade-session": TOKEN}}, None)["statusCode"] == 400


def test_requires_identity():
    assert call(JOB, token=None)["statusCode"] == 401


def test_other_owner_sees_not_found():
    r = call(JOB, token="u" * 40)
    assert r["statusCode"] == 404 and "hi" not in r["body"]


def test_job_without_owner_is_not_readable():
    assert call(LEGACY)["statusCode"] == 404


def test_signed_in_owner():
    event = {"pathParameters": {"id": JOB}, "requestContext": {"authorizer": {"jwt": {"claims": {"sub": "u1"}}}}}
    assert app.lambda_handler(event, None)["statusCode"] == 404  # owned by a session token, not by u1
