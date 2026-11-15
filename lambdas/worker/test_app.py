import importlib.util
import json
import os

import pytest
from botocore.exceptions import ClientError

_spec = importlib.util.spec_from_file_location("worker_app", os.path.join(os.path.dirname(__file__), "app.py"))
app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(app)


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


class FakeAgent:
    def __init__(self, completion=None, error=None):
        self.completion = completion
        self.error = error
        self.calls = []

    def invoke_agent(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return {"completion": self.completion}


class FakeS3:
    def __init__(self):
        self.puts = []

    def put_object(self, **kw):
        self.puts.append(kw)


def tr(**kw):
    return {"trace": {"trace": kw}}


def fake_stream():
    return [
        tr(
            orchestrationTrace={
                "invocationInput": {
                    "actionGroupInvocationInput": {
                        "actionGroupName": "cascade-tools",
                        "function": "get_portfolio_beta",
                        "parameters": [{"name": "persona", "type": "string", "value": "robert"}],
                    }
                }
            }
        ),
        tr(
            orchestrationTrace={
                "observation": {"actionGroupInvocationOutput": {"text": "x" * 3000}},
            }
        ),
        tr(
            orchestrationTrace={
                "observation": {
                    "knowledgeBaseLookupOutput": {
                        "retrievedReferences": [
                            {
                                "content": {"text": "Duration is 14.63 years"},
                                "location": {"type": "S3", "s3Location": {"uri": "s3://b/doc.pdf"}},
                            }
                        ]
                    }
                }
            }
        ),
        tr(guardrailTrace={"action": "INTERVENED", "outputAssessments": [{"topicPolicy": {}}]}),
        tr(guardrailTrace={"action": "NONE"}),
        {"chunk": {"bytes": b"Oil beta "}},
        {
            "chunk": {
                "bytes": b"is 0.2.",
                "attribution": {
                    "citations": [
                        {
                            "retrievedReferences": [
                                {
                                    "content": {"text": "Duration is 14.63 years"},
                                    "location": {"s3Location": {"uri": "s3://b/doc.pdf"}},
                                },
                                {
                                    "content": {"text": "other"},
                                    "location": {"s3Location": {"uri": "s3://b/other.pdf"}},
                                },
                            ]
                        }
                    ]
                },
            }
        },
    ]


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("AGENT_ID", "AG")
    monkeypatch.setenv("AGENT_ALIAS_ID", "AL")
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


def test_parse_stream():
    answer, traces, calls, cites, guards = app.parse_stream(fake_stream())
    assert answer == "Oil beta is 0.2."
    assert len(traces) == 5
    assert calls == [
        {
            "function": "get_portfolio_beta",
            "actionGroup": "cascade-tools",
            "parameters": {"persona": "robert"},
            "response": "x" * (app.MAX_TOOL_RESPONSE - 3) + "...",
        }
    ]
    assert [c["source"] for c in cites] == ["s3://b/doc.pdf", "s3://b/other.pdf"]
    assert len(guards) == 1


def test_done_path(setup):
    make, item, s3 = setup
    agent = FakeAgent(fake_stream())
    t = make(agent)
    assert app.lambda_handler(event(), None) == {"batchItemFailures": []}
    kw = agent.calls[0]
    assert kw["agentId"] == "AG" and kw["agentAliasId"] == "AL" and kw["sessionId"] == "sess"
    assert kw["inputText"] == "Q?" and kw["enableTrace"] is True
    assert kw["sessionState"] == {"promptSessionAttributes": {"persona": "robert", "level": "beginner"}}
    assert s3.puts[0]["Bucket"] == "cascade-s3-bucket" and s3.puts[0]["Key"] == "traces/j1.json"
    saved = json.loads(s3.puts[0]["Body"])
    assert saved["answer"] == "Oil beta is 0.2." and len(saved["guardrails"]) == 1
    assert item["status"] == "DONE"
    assert item["answer"] == "Oil beta is 0.2."
    assert item["traceKey"] == "traces/j1.json"
    assert len(item["toolCalls"]) == 1 and len(item["citations"]) == 2
    assert isinstance(item["durationMs"], int) and item["finishedAt"]


def test_limits_and_truncation(setup):
    make, item, s3 = setup
    stream = [{"chunk": {"bytes": b"a" * 200_000}}]
    for i in range(30):
        stream.append(tr(orchestrationTrace={"invocationInput": {"actionGroupInvocationInput": {"function": "f%d" % i}}}))
        stream.append(tr(orchestrationTrace={"observation": {"knowledgeBaseLookupOutput": {"retrievedReferences": [
            {"content": {"text": "t%d" % i}, "location": {"s3Location": {"uri": "s3://b/%d" % i}}}]}}}))
    make(FakeAgent(stream))
    app.lambda_handler(event(), None)
    assert len(item["toolCalls"]) == 20
    assert len(item["citations"]) == 10
    assert len(item["answer"]) == app.MAX_ANSWER and item["answer"].endswith("...")


def test_race_condition_skipped(setup):
    make, item, s3 = setup
    agent = FakeAgent(fake_stream())
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
    make(FakeAgent(fake_stream()), FakeTable(None))
    assert app.lambda_handler(event(), None) == {"batchItemFailures": []}


def test_log_has_no_question(setup, capsys):
    make, item, s3 = setup
    make(FakeAgent(fake_stream()))
    app.lambda_handler(event(), None)
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["jobId"] == "j1" and line["status"] == "DONE" and "durationMs" in line
    assert "Q?" not in json.dumps(line)
