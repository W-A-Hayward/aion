import importlib.util
import json
import os
import uuid

import pytest
from botocore.exceptions import ClientError

_spec = importlib.util.spec_from_file_location("submit_app", os.path.join(os.path.dirname(__file__), "app.py"))
app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(app)


class FakeTable:
    """Jobs go to .items; rate counters (update_item on "rate#..." keys) go to .counters."""

    def __init__(self):
        self.items = []
        self.counters = {}
        self.job_updates = []

    def put_item(self, Item):
        self.items.append(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues, **kw):
        key = Key["jobId"]
        if not key.startswith("rate#"):
            self.job_updates.append((key, ExpressionAttributeValues))
            return
        n = self.counters.get(key, 0)
        if n >= ExpressionAttributeValues[":limit"]:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "m"}}, "UpdateItem")
        self.counters[key] = n + 1


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


TOKEN = "t" * 40


def ev(body, token=TOKEN, ip="203.0.113.7"):
    event = {"body": json.dumps(body) if not isinstance(body, str) else body,
             "requestContext": {"http": {"method": "POST", "sourceIp": ip}}}
    if token is not None:
        event["headers"] = {"X-Cascade-Session": token}
    return event


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
    assert json.loads(q.sent[0][1]) == {"jobId": body["jobId"], "level": "beginner", "experiment_id": None}
    assert [s["stage"] for s in item["stages"]] == ["queued"] and "experimentId" not in item


def test_experiment_id_goes_through_sqs_and_job_row(env):
    t, q = env
    r = app.lambda_handler(ev(dict(GOOD, level="expert", experiment_id="bonds_protect")), None)
    assert r["statusCode"] == 202
    assert json.loads(q.sent[0][1]) == {"jobId": json.loads(r["body"])["jobId"], "level": "expert",
                                        "experiment_id": "bonds_protect"}
    assert t.items[0]["experimentId"] == "bonds_protect"


@pytest.mark.parametrize("bad", ["", "a b", "x" * 65, 5, "a#b"])
def test_bad_experiment_id(env, bad):
    assert app.lambda_handler(ev(dict(GOOD, experiment_id=bad)), None)["statusCode"] == 400
    assert env[0].items == [] and env[1].sent == []


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
    r = app.lambda_handler(dict(ev({}), body=body), None)
    assert r["statusCode"] == 400


def test_max_length_question_ok(env):
    r = app.lambda_handler(ev(dict(GOOD, question="x" * 1000)), None)
    assert r["statusCode"] == 202


# --- access control and reliability ------------------------------------------

@pytest.mark.parametrize("token", [None, "", "short", "x" * 129, "bad token with spaces" * 3])
def test_requires_owner_identity(env, token):
    r = app.lambda_handler(ev(GOOD, token=token), None)
    assert r["statusCode"] == 401
    assert env[0].items == [] and env[1].sent == []


def test_owner_hash_stored_not_token(env):
    t, _ = env
    app.lambda_handler(ev(GOOD), None)
    item = t.items[0]
    assert len(item["ownerHash"]) == 64 and TOKEN not in json.dumps(item)
    assert item["agentSessionId"].startswith(item["ownerHash"][:16] + "-")


def test_signed_in_user_owns_job_without_token(env):
    event = ev(GOOD, token=None)
    event["requestContext"]["authorizer"] = {"jwt": {"claims": {"sub": "user-123"}}}
    r = app.lambda_handler(event, None)
    assert r["statusCode"] == 202
    assert env[0].items[0]["ownerHash"] == app.owner_of(event)


def test_rate_limit_per_owner(env, monkeypatch):
    monkeypatch.setenv("RATE_PER_OWNER_PER_MIN", "2")
    codes = [app.lambda_handler(ev(GOOD), None)["statusCode"] for _ in range(3)]
    assert codes == [202, 202, 429]
    assert len(env[0].items) == 2
    # A different browser on the same IP is not blocked by the first one's limit.
    assert app.lambda_handler(ev(GOOD, token="u" * 40), None)["statusCode"] == 202


def test_rate_limit_per_ip(env, monkeypatch):
    monkeypatch.setenv("RATE_PER_IP_PER_MIN", "2")
    codes = [app.lambda_handler(ev(GOOD, token=c * 40), None)["statusCode"] for c in "abc"]
    assert codes == [202, 202, 429]
    r = app.lambda_handler(ev(GOOD, token="d" * 40), None)
    assert r["headers"]["retry-after"] == "60"


def test_rate_window_resets(env):
    assert app.take_rate_token("owner", "k", 1, now=0)
    assert not app.take_rate_token("owner", "k", 1, now=59)
    assert app.take_rate_token("owner", "k", 1, now=60)


def test_enqueue_failure_marks_job_failed(env):
    t, q = env

    def boom(**kw):
        raise RuntimeError("sqs down")

    q.send_message = boom
    r = app.lambda_handler(ev(GOOD), None)
    assert r["statusCode"] == 503
    job_id = t.items[0]["jobId"]
    assert t.job_updates and t.job_updates[0][0] == job_id
    assert t.job_updates[0][1][":failed"] == "FAILED"


def test_cors_header_when_configured(env, monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGIN", "https://cascade.example")
    r = app.lambda_handler(ev(GOOD), None)
    assert r["headers"]["access-control-allow-origin"] == "https://cascade.example"
    monkeypatch.delenv("ALLOWED_ORIGIN")
    assert "access-control-allow-origin" not in app.lambda_handler(ev(GOOD, token="z" * 40), None)["headers"]


def test_preflight(env):
    r = app.lambda_handler({"requestContext": {"http": {"method": "OPTIONS"}}}, None)
    assert r["statusCode"] == 204 and env[0].items == []


def test_custom_portfolio_is_stored_with_the_job(env):
    t, q = env
    holdings = [{"ticker": "XIU.TO", "weight": 0.6}, {"ticker": "ENB.TO", "weight": 0.4}]
    r = app.lambda_handler(ev(dict(GOOD, persona="custom", holdings=holdings)), None)
    assert r["statusCode"] == 202
    item = t.items[0]
    assert item["persona"] == "custom"
    assert json.loads(item["holdings"]) == holdings
    assert all(not isinstance(v, float) for v in item.values()), "DynamoDB items must not hold raw floats"


def test_sample_persona_job_has_no_holdings(env):
    t, _ = env
    app.lambda_handler(ev(GOOD), None)
    assert "holdings" not in t.items[0]
