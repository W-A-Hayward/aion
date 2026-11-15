import importlib.util
import json
import os

import pytest
from botocore.exceptions import ClientError

_spec = importlib.util.spec_from_file_location("worker_app", os.path.join(os.path.dirname(__file__), "app.py"))
app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(app)


ARN = "arn:aws:bedrock-agentcore:us-east-1:339713040194:runtime/cascade_agent-AbCdEfGhIj"


def cerr(code, op="Op"):
    return ClientError({"Error": {"Code": code, "Message": "m"}}, op)


class FakeTable:
    def __init__(self, item, claim_error=None):
        self.item = item
        self.claim_error = claim_error
        self.updates = []

    def get_item(self, Key):
        return {"Item": self.item} if self.item else {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues, **kw):
        if "ConditionExpression" in kw:
            if self.claim_error:
                raise self.claim_error
            self.item["status"] = ExpressionAttributeValues[":running"]
            return
        fields = {}
        for ph, name in ExpressionAttributeNames.items():
            if ph == "#s":
                fields["status"] = ExpressionAttributeValues[":s"]
            else:
                fields[name] = ExpressionAttributeValues[":v" + ph[2:]]
        self.updates.append(fields)
        self.item.update(fields)


class FakeBody:
    def __init__(self, data):
        self.data = data if isinstance(data, bytes) else json.dumps(data).encode("utf-8")

    def read(self):
        return self.data


class FakeAgent:
    def __init__(self, body=None, error=None):
        self.body = body
        self.error = error
        self.calls = []

    def invoke_agent_runtime(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return {"response": FakeBody(self.body), "statusCode": 200}


class FakeS3:
    def __init__(self):
        self.puts = []

    def put_object(self, **kw):
        self.puts.append(kw)


def fake_body():
    return {
        "answer": "Oil beta is 0.2.",
        "toolCalls": [
            {"name": "get_portfolio_exposure", "input": {"persona": "robert"}, "output": "ok"}
        ],
        "citations": [
            {"text": "Duration is 14.63 years", "source_url": "https://example.com/tlt.pdf", "section": "Fund facts",
             "ticker": "TLT", "channel": "rates"},
            {"text": "other", "source_url": None, "section": None, "ticker": "XOM", "channel": "direct"},
        ],
        "extra": {"beta": 0.25},
    }


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("AGENT_RUNTIME_ARN", ARN)
    monkeypatch.setenv("BUCKET", "cascade-s3-bucket")
    item = {"jobId": "j1", "status": "PENDING", "question": "Q?", "persona": "robert",
            "level": "beginner", "sessionId": "sess"}
    s3 = FakeS3()
    monkeypatch.setattr(app, "_s3", lambda: s3)

    def make(agent, table=None):
        t = table or FakeTable(item)
        monkeypatch.setattr(app, "_table", lambda: t)
        monkeypatch.setattr(app, "_agent", lambda: agent)
        return t

    return make, item, s3


def event(job="j1", mid="m1"):
    return {"Records": [{"messageId": mid, "body": json.dumps({"jobId": job})}]}


def test_session_id_padding():
    assert app.session_id_for("sess") == "cascade-sess" + "-" * 21
    assert len(app.session_id_for("sess")) == 33
    long = "a" * 40
    assert app.session_id_for(long) == "cascade-" + long


def test_done_path(setup):
    make, item, s3 = setup
    agent = FakeAgent(fake_body())
    make(agent)
    assert app.lambda_handler(event(), None) == {"batchItemFailures": []}
    kw = agent.calls[0]
    assert kw["agentRuntimeArn"] == ARN
    assert kw["runtimeSessionId"] == "cascade-sess" + "-" * 21
    assert json.loads(kw["payload"]) == {"question": "Q?", "persona": "robert", "level": "beginner"}
    assert s3.puts[0]["Bucket"] == "cascade-s3-bucket" and s3.puts[0]["Key"] == "traces/j1.json"
    saved = json.loads(s3.puts[0]["Body"])
    assert saved["jobId"] == "j1" and saved["response"] == fake_body()
    assert item["status"] == "DONE"
    assert item["answer"] == "Oil beta is 0.2."
    assert item["traceKey"] == "traces/j1.json"
    assert len(item["toolCalls"]) == 1 and len(item["citations"]) == 2
    assert isinstance(item["durationMs"], int) and item["finishedAt"]


def test_guardrail_saved_when_present(setup):
    make, item, s3 = setup
    body = fake_body()
    body["guardrail"] = {"action": "INTERVENED"}
    make(FakeAgent(body))
    app.lambda_handler(event(), None)
    assert item["guardrail"] == {"action": "INTERVENED"}


def test_guardrail_absent_by_default(setup):
    make, item, s3 = setup
    make(FakeAgent(fake_body()))
    app.lambda_handler(event(), None)
    assert "guardrail" not in item


def test_floats_become_decimal(setup):
    make, item, s3 = setup
    body = fake_body()
    body["toolCalls"][0]["input"] = {"beta": 0.25}
    make(FakeAgent(body))
    app.lambda_handler(event(), None)
    assert item["toolCalls"][0]["input"]["beta"] == app.Decimal("0.25")
    assert json.loads(s3.puts[0]["Body"])["response"]["toolCalls"][0]["input"]["beta"] == 0.25


def test_plain_text_body(setup):
    make, item, s3 = setup
    make(FakeAgent(b"just text"))
    app.lambda_handler(event(), None)
    assert item["status"] == "DONE" and item["answer"] == "just text"
    assert item["toolCalls"] == [] and item["citations"] == []


def test_limits_and_truncation(setup):
    make, item, s3 = setup
    body = {
        "answer": "a" * 200_000,
        "toolCalls": [{"name": "f%d" % i, "input": {}, "output": ""} for i in range(30)],
        "citations": [{"text": "t", "source_url": "https://example.com/%d" % i} for i in range(30)],
    }
    make(FakeAgent(body))
    app.lambda_handler(event(), None)
    assert len(item["toolCalls"]) == 20
    assert len(item["citations"]) == 10
    assert len(item["answer"]) == app.MAX_ANSWER and item["answer"].endswith("...")


def test_race_condition_skipped(setup):
    make, item, s3 = setup
    agent = FakeAgent(fake_body())
    make(agent, FakeTable(item, claim_error=cerr("ConditionalCheckFailedException")))
    assert app.lambda_handler(event(), None) == {"batchItemFailures": []}
    assert agent.calls == [] and s3.puts == []


def test_failed_path(setup):
    make, item, s3 = setup
    make(FakeAgent(error=ValueError("boom " + "x" * 800)))
    assert app.lambda_handler(event(), None) == {"batchItemFailures": []}
    assert item["status"] == "FAILED"
    assert item["error"].startswith("ValueError: boom") and len(item["error"]) <= 500


def test_failed_on_stream_error(setup):
    make, item, s3 = setup
    make(FakeAgent(error=cerr("AccessDeniedException")))
    assert app.lambda_handler(event(), None) == {"batchItemFailures": []}
    assert item["status"] == "FAILED"


def test_throttling_retried(setup):
    make, item, s3 = setup
    make(FakeAgent(error=cerr("throttlingException")))
    assert app.lambda_handler(event(mid="m9"), None) == {"batchItemFailures": [{"itemIdentifier": "m9"}]}
    assert item["status"] == "PENDING"


def test_missing_job_is_handled(setup):
    make, item, s3 = setup
    make(FakeAgent(fake_body()), FakeTable(None))
    assert app.lambda_handler(event(), None) == {"batchItemFailures": []}


def test_log_has_no_question(setup, capsys):
    make, item, s3 = setup
    make(FakeAgent(fake_body()))
    app.lambda_handler(event(), None)
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["jobId"] == "j1" and line["status"] == "DONE" and "durationMs" in line
    assert "Q?" not in json.dumps(line)


def test_agent_session_is_owner_scoped(setup):
    make, item, s3 = setup
    item["agentSessionId"] = "0123456789abcdef-sess"
    agent = FakeAgent(fake_body())
    make(agent)
    app.lambda_handler(event(), None)
    assert agent.calls[0]["runtimeSessionId"] == app.session_id_for("0123456789abcdef-sess")
    assert agent.calls[0]["runtimeSessionId"].startswith("cascade-0123456789abcdef-sess")


def test_claim_allows_reclaiming_stale_running_job(setup, monkeypatch):
    make, item, s3 = setup
    seen = {}

    class Recording(FakeTable):
        def update_item(self, Key, UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues, **kw):
            if "ConditionExpression" in kw:
                seen.update(kw, values=ExpressionAttributeValues)
            return super().update_item(Key, UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues, **kw)

    monkeypatch.setattr(app.time, "time", lambda: 10_000)
    make(FakeAgent(fake_body()), Recording(item))
    app.lambda_handler(event(), None)
    assert "#s = :running AND startedAtEpoch < :stale" in seen["ConditionExpression"]
    assert seen["values"][":stale"] == 10_000 - app.STALE_RUNNING_SECONDS
    assert seen["values"][":now"] == 10_000
