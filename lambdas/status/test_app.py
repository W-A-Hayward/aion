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
            }
        }
    )
    monkeypatch.setattr(app, "_table", lambda: t)


def call(i):
    return app.lambda_handler({"pathParameters": {"id": i}}, None)


def test_done():
    r = call(JOB)
    assert r["statusCode"] == 200
    body = json.loads(r["body"])
    assert body["status"] == "DONE" and body["answer"] == "hi" and body["durationMs"] == 1234
    assert "question" not in body and "sessionId" not in body and "traceKey" not in body


def test_not_found():
    assert call(OTHER)["statusCode"] == 404


@pytest.mark.parametrize("bad", ["abc", "", None, "../x", JOB + "x", JOB.replace("-", "")])
def test_invalid_id(bad):
    assert call(bad)["statusCode"] == 400


def test_missing_path_params():
    assert app.lambda_handler({}, None)["statusCode"] == 400
