import importlib.util
import json
import os
import uuid

import pytest

_spec = importlib.util.spec_from_file_location("submit_app", os.path.join(os.path.dirname(__file__), "app.py"))
app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(app)


class FakeTable:
    def __init__(self):
        self.items = []

    def put_item(self, Item):
        self.items.append(Item)


class FakeSqs:
    def __init__(self):
        self.sent = []

    def send_message(self, QueueUrl, MessageBody):
        self.sent.append((QueueUrl, MessageBody))


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("QUEUE_URL", "https://sqs/agent-jobs")
    t, q = FakeTable(), FakeSqs()
    monkeypatch.setattr(app, "_table", lambda: t)
    monkeypatch.setattr(app, "_sqs", lambda: q)
    return t, q


def ev(body):
    return {"body": json.dumps(body) if not isinstance(body, str) else body}


GOOD = {"question": "How exposed am I to oil?", "persona": "robert", "level": "beginner"}


def test_happy_path(env):
    t, q = env
    r = app.lambda_handler(ev(GOOD), None)
    assert r["statusCode"] == 202
    body = json.loads(r["body"])
    uuid.UUID(body["jobId"])
    uuid.UUID(body["sessionId"])
    item = t.items[0]
    assert item["status"] == "PENDING" and item["jobId"] == body["jobId"]
    assert item["sessionId"] == body["sessionId"]
    assert isinstance(item["expiresAt"], int)
    assert json.loads(q.sent[0][1]) == {"jobId": body["jobId"]}


def test_given_session_id(env):
    r = app.lambda_handler(ev(dict(GOOD, sessionId="abc-123")), None)
    assert json.loads(r["body"])["sessionId"] == "abc-123"


@pytest.mark.parametrize(
    "patch",
    [
        {"question": ""},
        {"question": "x" * 1001},
        {"question": 5},
        {"persona": "bob"},
        {"level": "pro"},
        {"sessionId": "bad id!"},
        {"sessionId": "a" * 101},
        {"sessionId": 7},
    ],
)
def test_validation_errors(env, patch):
    r = app.lambda_handler(ev(dict(GOOD, **patch)), None)
    assert r["statusCode"] == 400
    assert "error" in json.loads(r["body"])
    assert env[0].items == [] and env[1].sent == []


@pytest.mark.parametrize("body", ["not json", "[1]", None])
def test_bad_body(env, body):
    r = app.lambda_handler({"body": body}, None)
    assert r["statusCode"] == 400


def test_max_length_question_ok(env):
    r = app.lambda_handler(ev(dict(GOOD, question="x" * 1000)), None)
    assert r["statusCode"] == 202
