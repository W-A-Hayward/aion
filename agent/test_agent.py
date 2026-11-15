"""Tests for agent.agent. No AWS calls: boto3 clients are mocked."""
import io
import json
import os
import sys
import types
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Stub the runtime packages only when they are not installed.
try:
    import bedrock_agentcore.runtime  # noqa: F401
except ImportError:
    pkg = types.ModuleType("bedrock_agentcore")
    rt = types.ModuleType("bedrock_agentcore.runtime")

    class _App:
        def entrypoint(self, fn):
            return fn

        def run(self):
            pass

    rt.BedrockAgentCoreApp = _App
    sys.modules["bedrock_agentcore"] = pkg
    sys.modules["bedrock_agentcore.runtime"] = rt

try:
    import strands  # noqa: F401
    import strands.models  # noqa: F401
except ImportError:
    st = types.ModuleType("strands")
    sm = types.ModuleType("strands.models")
    st.tool = lambda fn: fn
    st.Agent = object
    sm.BedrockModel = object
    st.models = sm
    sys.modules["strands"] = st
    sys.modules["strands.models"] = sm

import agent as ag  # noqa: E402


def _call(fn, *args, **kwargs):
    """Call a @tool-decorated function whether or not it is wrapped."""
    target = getattr(fn, "_tool_func", fn)
    return target(*args, **kwargs)


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    ag._tool_calls.clear()
    ag._citations.clear()
    monkeypatch.setattr(ag, "_instructions", "INSTRUCTIONS")
    yield


def _lambda_response(body_obj):
    outer = {"response": {"functionResponse": {"responseBody": {"TEXT": {"body": json.dumps(body_obj)}}}}}
    return {"Payload": io.BytesIO(json.dumps(outer).encode())}


def test_tool_returns_parsed_body_and_sends_event(monkeypatch):
    client = mock.Mock()
    client.invoke.return_value = _lambda_response({"persona": "robert", "holdings": []})
    monkeypatch.setattr(ag, "_lambda_client", client)

    out = _call(ag.get_portfolio_exposure, "robert")

    assert out == {"persona": "robert", "holdings": []}
    kwargs = client.invoke.call_args.kwargs
    assert kwargs["FunctionName"] == "cascade-tools"
    event = json.loads(kwargs["Payload"])
    assert event["actionGroup"] == "oil-tools"
    assert event["function"] == "get_portfolio_exposure"
    assert event["parameters"] == [{"name": "persona", "type": "string", "value": "robert"}]
    assert ag._tool_calls[0]["name"] == "get_portfolio_exposure"


def test_scenario_params_are_strings(monkeypatch):
    client = mock.Mock()
    client.invoke.return_value = _lambda_response({"ok": 1})
    monkeypatch.setattr(ag, "_lambda_client", client)
    _call(ag.run_scenario, "amira", -30)
    event = json.loads(client.invoke.call_args.kwargs["Payload"])
    assert {"name": "oil_shock_pct", "type": "string", "value": "-30"} in event["parameters"]


def test_explain_channel_collects_citations(monkeypatch):
    client = mock.Mock()
    client.invoke.return_value = _lambda_response({"evidence": [
        {"ticker": "TLT", "channel": "rates", "source_url": "http://x", "section": "p3", "excerpt": "e"}]})
    monkeypatch.setattr(ag, "_lambda_client", client)
    _call(ag.explain_channel, "TLT")
    assert ag._citations == [
        {"text": "e", "source_url": "http://x", "section": "p3", "ticker": "TLT", "channel": "rates"}]


def test_search_evidence_filter_and_rows(monkeypatch):
    kb = mock.Mock()
    kb.retrieve.return_value = {"retrievalResults": [
        {"content": {"text": "hello"},
         "metadata": {"source_url": "http://y", "section": "s", "ticker": "ENB.TO", "channel": "direct"}}]}
    monkeypatch.setattr(ag, "_kb_client", kb)
    rows = _call(ag.search_evidence, "tariffs", "ENB.TO")
    cfg = kb.retrieve.call_args.kwargs["retrievalConfiguration"]["vectorSearchConfiguration"]
    assert cfg["numberOfResults"] == 3
    assert cfg["filter"] == {"equals": {"key": "ticker", "value": "ENB.TO"}}
    assert rows == [{"text": "hello", "source_url": "http://y", "section": "s",
                     "ticker": "ENB.TO", "channel": "direct"}]
    assert len(ag._citations) == 1


def test_entrypoint_returns_four_keys(monkeypatch):
    class FakeAgent:
        def __init__(self, model=None, tools=None, system_prompt=None, callback_handler=None):
            FakeAgent.system_prompt = system_prompt

        def __call__(self, question):
            ag._record_call("get_validation", {"ticker": "TLT"}, {"x": 1})
            return "final answer"

    monkeypatch.setattr(ag, "Agent", FakeAgent)
    monkeypatch.setattr(ag, "_build_model", lambda: object())

    out = ag.invoke({"question": "q", "persona": "robert", "level": "advanced"})

    assert set(out) == {"answer", "toolCalls", "citations", "usage"}
    assert out["answer"] == "final answer"
    assert out["toolCalls"][0]["name"] == "get_validation"
    assert FakeAgent.system_prompt == "INSTRUCTIONS\nPersona: robert\nLevel: advanced"


def test_build_model_guards_latest_message_only(monkeypatch):
    captured = {}

    class FakeModel:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(ag, "BedrockModel", FakeModel)
    monkeypatch.setattr(ag, "GUARDRAIL_ID", "gid")
    monkeypatch.setattr(ag, "GUARDRAIL_VERSION", "1")
    ag._build_model()
    assert captured["guardrail_latest_message"] is True
    assert captured["guardrail_id"] == "gid"
    assert captured["guardrail_version"] == "1"
    assert captured["guardrail_trace"] == "enabled"


INPUT_TRACE = {"inputAssessment": {"gid": {
    "topicPolicy": {"topics": [{"name": "Stock tips", "type": "DENY", "action": "BLOCKED"},
                               {"name": "Other", "type": "DENY", "action": "NONE"}]},
    "contentPolicy": {"filters": [{"type": "INSULTS", "confidence": "HIGH", "action": "BLOCKED"}]},
    "wordPolicy": {"customWords": [{"match": "badword", "action": "BLOCKED"}],
                   "managedWordLists": [{"match": "prof", "type": "PROFANITY", "action": "BLOCKED"}]},
    "sensitiveInformationPolicy": {"piiEntities": [{"type": "EMAIL", "match": "a@b.c", "action": "ANONYMIZED"}]},
}}}
OUTPUT_TRACE = {"outputAssessments": {"gid": [{
    "contextualGroundingPolicy": {"filters": [
        {"type": "GROUNDING", "threshold": 0.8, "score": 0.4, "action": "BLOCKED"},
        {"type": "RELEVANCE", "threshold": 0.5, "score": 0.9, "action": "NONE"}]},
}]}}


def test_summarize_guardrail_input_and_output():
    assert ag.summarize_guardrail(INPUT_TRACE) == [{
        "source": "INPUT",
        "topics": ["Stock tips"],
        "content_filters": ["INSULTS"],
        "words": ["badword", "prof"],
        "sensitive_information": ["EMAIL"],
    }]
    assert ag.summarize_guardrail(OUTPUT_TRACE) == [{
        "source": "OUTPUT",
        "contextual_grounding": [{"type": "GROUNDING", "score": 0.4, "threshold": 0.8}],
    }]


def test_summarize_apply_guardrail_response():
    resp = {"action": "GUARDRAIL_INTERVENED", "assessments": [INPUT_TRACE["inputAssessment"]["gid"]]}
    recs = ag.summarize_guardrail(resp, source="INPUT")
    assert recs[0]["source"] == "INPUT" and recs[0]["topics"] == ["Stock tips"]
    assert ag.summarize_guardrail({"assessments": [{}]}, source="INPUT") == []


def test_entrypoint_returns_and_logs_guardrail(monkeypatch, capsys):
    class FakeAgent:
        def __init__(self, model=None, tools=None, system_prompt=None, callback_handler=None):
            self.cb = callback_handler

        def __call__(self, question):
            self.cb(event={"metadata": {"trace": {"guardrail": OUTPUT_TRACE}}})
            self.cb(data="text")
            return "blocked"

    monkeypatch.setattr(ag, "Agent", FakeAgent)
    monkeypatch.setattr(ag, "_build_model", lambda: object())
    out = ag.invoke({"question": "q", "persona": "robert", "level": "advanced"})
    assert out["guardrail"] == [{
        "source": "OUTPUT",
        "contextual_grounding": [{"type": "GROUNDING", "score": 0.4, "threshold": 0.8}],
    }]
    logged = [json.loads(l) for l in capsys.readouterr().out.splitlines() if l.startswith("{")]
    assert {"guardrail": out["guardrail"]} in logged
