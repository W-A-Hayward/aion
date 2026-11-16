import importlib.util
import json
import os

import pytest
from botocore.exceptions import ClientError

_spec = importlib.util.spec_from_file_location("worker_app", os.path.join(os.path.dirname(__file__), "app.py"))
app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(app)


ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/cascade_agent-AbCdEfGhIj"


def cerr(code, op="Op"):
    return ClientError({"Error": {"Code": code, "Message": "m"}}, op)


class FakeTable:
    """Jobs and cache items by jobId. update_item understands the worker's three kinds of update."""

    def __init__(self, item, claim_error=None, extra=None):
        self.items = {item["jobId"]: item} if item else {}
        self.items.update(extra or {})
        self.item = item
        self.claim_error = claim_error
        self.updates = []

    def get_item(self, Key):
        found = self.items.get(Key["jobId"])
        return {"Item": found} if found else {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ExpressionAttributeNames=None, **kw):
        if Key["jobId"].startswith("cache#"):
            self.items[Key["jobId"]] = {"jobId": Key["jobId"], "sourceJobId": ExpressionAttributeValues[":j"],
                                        "expiresAt": ExpressionAttributeValues[":e"]}
            return
        job = self.items[Key["jobId"]]
        if "ConditionExpression" in kw:
            if self.claim_error:
                raise self.claim_error
            job["status"] = ExpressionAttributeValues[":running"]
            return
        fields = {}
        for ph, name in ExpressionAttributeNames.items():
            if ph == "#s":
                fields["status"] = ExpressionAttributeValues[":s"]
            elif ph == "#stg":
                job["stages"] = list(job.get("stages") or []) + ExpressionAttributeValues[":stg"]
            else:
                fields[name] = ExpressionAttributeValues[":v" + ph[2:]]
        self.updates.append(fields)
        job.update(fields)


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


EVIDENCE = [
    {"evidence_id": "bis-01", "topic": "stock_bond", "publisher": "BIS", "date": "2023-12",
     "trust": "Central bank", "source_url": "https://www.bis.org/a", "excerpt": "bis excerpt"},
    {"evidence_id": "fed-02", "topic": "stock_bond", "publisher": "Federal Reserve", "date": "2026-10",
     "trust": "Central bank", "source_url": "https://www.federalreserve.gov/b", "excerpt": "fed excerpt"},
]
FACTS = {
    "persona": "robert",
    "risk_share": {"rates": 0.707, "stocks": 0.19, "oil": 0.026},
    "shields": [{"item": "usdcad", "label": "WORKING", "avg_pct_worst": 0.56, "weeks_up": 20, "weeks": 26}],
    "cushion_top": [{"candidate": "usdcad", "avg_pct_worst": 0.56, "weeks_up": 20, "weeks": 26, "binom_p": 0.01},
                    {"candidate": "GLD", "avg_pct_worst": -0.58, "weeks_up": 10, "weeks": 26, "binom_p": 0.3}],
    "betas": [{"ticker": "TLT", "weight": 0.3, "oil": {"beta": -0.1, "lo": -0.2, "hi": 0.0}, "rates": None}],
    "twin_series": {"months": ["2025-03", "2025-04"], "persona": [-1.0, -15.1], "twin": [-2.0, -19.2]},
    "stock_bond": {
        "by_cpi_regime": {"XIU.TO/XBB.TO": {"cpi_ge_3": {"corr": 0.417, "n_weeks": 58},
                                            "cpi_lt_3": {"corr": 0.072, "n_weeks": 151}}},
        "rolling_52w_monthly": {"months": ["2025-03", "2025-04"], "XIU.TO/XBB.TO": [0.1, None]},
    },
    "evidence": EVIDENCE,
}
SCENARIO = {"persona": "robert", "shock_type": "oil", "oil_shock_pct": 15,
            "scenario": [{"subject": "robert", "subject_type": "persona", "shock_pct": 15, "impact_pct": -1.2,
                          "lo_pct": -3.0, "hi_pct": 0.5}]}
TRACE = [
    {"step": 1, "tool": "get_portfolio_facts", "input_summary": "persona=robert",
     "output_summary": "risk_share rates 0.707", "tag": "measured", "ms": 2100},
    {"step": 2, "tool": "run_scenario", "input_summary": "persona=robert, oil_shock_pct=15",
     "output_summary": "oil 15%: -1.20%", "tag": "measured", "ms": 900},
]


def fake_body(answer="MYTH Tes obligations n'ont pas protege. Details [fed-02] et [bis-01] puis [fed-02]."):
    return {
        "answer_text": answer,
        "trace": TRACE,
        "tool_results": {"get_portfolio_facts": [FACTS], "run_scenario": [SCENARIO]},
        "toolCalls": [{"name": "get_portfolio_facts", "input": {"persona": "robert"}, "output": "ok"}],
        "claims": [{"persona": "robert", "impact_pct": -1.2, "shock_pct": 15}],
    }


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("AGENT_RUNTIME_ARN", ARN)
    monkeypatch.setenv("BUCKET", "cascade-s3-bucket")
    item = {"jobId": "j1", "status": "PENDING", "question": "Q?", "persona": "robert",
            "level": "beginner", "sessionId": "sess", "expiresAt": 5000,
            "stages": [{"stage": "queued", "t": "2026-11-15T14:02:03Z"}]}
    s3 = FakeS3()
    monkeypatch.setattr(app, "_s3", lambda: s3)

    def make(agent, table=None):
        t = table or FakeTable(item)
        monkeypatch.setattr(app, "_table", lambda: t)
        monkeypatch.setattr(app, "_agent", lambda: agent)
        return t

    return make, item, s3


def event(job="j1", mid="m1", **extra):
    return {"Records": [{"messageId": mid, "body": json.dumps(dict({"jobId": job}, **extra))}]}


def test_session_id_padding():
    assert app.session_id_for("sess") == "cascade-sess" + "-" * 21
    assert len(app.session_id_for("sess")) == 33
    long = "a" * 40
    assert app.session_id_for(long) == "cascade-" + long


# ---- answer parsing -------------------------------------------------------------------------

@pytest.mark.parametrize("text,verdict,headline", [
    ("MYTH Tes obligations ont perdu. Suite.", "MYTH", "Tes obligations ont perdu."),
    ("NOT LINKED: RY.TO is not tied to oil. More.", "NOT LINKED", "RY.TO is not tied to oil."),
    ("**REAL** — Oil matters. Next sentence.", "REAL", "Oil matters."),
    ("MATERIALITY is unclear. Second.", None, "MATERIALITY is unclear."),
    ("Myth: lower case is not a verdict.", None, "Myth: lower case is not a verdict."),
    ("WORKING\nThe dollar cushioned 0.56 % of losses. More", "WORKING", "The dollar cushioned 0.56 % of losses."),
    ("The answer is MYTH. Rest.", None, "The answer is MYTH."),
])
def test_parse_answer_verdict_and_headline(text, verdict, headline):
    v, h, _, declined = app.parse_answer(text)
    assert (v, h, declined) == (verdict, headline, False)


@pytest.mark.parametrize("verdict", ["REAL", "MATERIAL", "MINOR", "MYTH", "NOT LINKED", "HIDDEN", "BROKEN",
                                     "REMOVED", "WORKING"])
def test_every_verdict_is_recognized(verdict):
    assert app.parse_answer(verdict + " Done.")[0] == verdict


def test_decline_marker():
    v, h, text, declined = app.parse_answer("[[DECLINE]] I cannot give advice. Ask about history.")
    assert declined and v is None and text == "I cannot give advice. Ask about history."
    assert h == "I cannot give advice."


def test_citations_renumbered_in_order_of_appearance():
    evidence = app.collect_evidence({"get_portfolio_facts": [FACTS]})
    text, cites = app.build_citations("A [fed-02] B [bis-01] C [fed-02] D [unknown] E [1]", evidence)
    assert text == "A [1] B [2] C [1] D [unknown] E [1]"
    assert [(c["n"], c["evidence_id"]) for c in cites] == [(1, "fed-02"), (2, "bis-01")]
    assert cites[0] == {"n": 1, "evidence_id": "fed-02", "excerpt": "fed excerpt", "publisher": "Federal Reserve",
                        "date": "2026-10", "doc_type": "research", "trust": "Central bank",
                        "url": "https://www.federalreserve.gov/b"}


def test_no_citation_without_evidence():
    text, cites = app.build_citations("Plain [x] text", {})
    assert text == "Plain [x] text" and cites == []


@pytest.mark.parametrize("guardrail,expected", [
    (None, False),
    ([], False),
    ([{"source": "INPUT", "topics": ["Stock tips"]}], True),
    ([{"source": "OUTPUT", "contextual_grounding": [{"type": "GROUNDING"}]}], True),
    ([{"source": "INPUT", "sensitive_information": ["EMAIL"]}], False),
    ({"action": "INTERVENED"}, True),
])
def test_guardrail_intervened(guardrail, expected):
    assert app.guardrail_intervened(guardrail) is expected


# ---- data -----------------------------------------------------------------------------------

def test_data_is_merged_from_tool_results_only():
    d = app.build_data({"get_portfolio_facts": [FACTS], "run_scenario": [SCENARIO],
                        "test_shield": [{"persona": "robert", "ticker": "GLD",
                                         "worst_weeks": {"label": "BROKEN", "avg_pct_worst": -0.58,
                                                         "weeks_up": 10, "weeks": 26, "binom_p": 0.3}}]})
    assert d["risk_share"] == {"rates": 0.707, "stocks": 0.19, "oil": 0.026}
    assert d["cushion"][0] == {"asset": "usdcad", "avg_return_pct": 0.56, "hit_weeks": 20, "n_weeks": 26}
    assert [s["item"] for s in d["shields"]] == ["usdcad", "GLD"]
    assert d["betas"][0]["subject"] == "TLT" and d["betas"][0]["beta"] == -0.1
    assert d["twin_series"][1] == {"week": "2025-04", "own": None, "twin": None,
                                   "own_dd_pct": -15.1, "twin_dd_pct": -19.2}
    measures = [(r["measure"], r["week"], r["correlation"]) for r in d["stock_bond_series"]]
    assert ("cpi_ge_3", None, 0.417) in measures and ("rolling_52w", "2025-03", 0.1) in measures
    assert len(d["stock_bond_series"]) == 3  # the None rolling value is skipped
    assert d["scenario"] == {"subject": "robert", "subject_type": "persona", "shock_pct": 15,
                             "impact_pct": -1.2, "lo_pct": -3.0, "hi_pct": 0.5}


def test_data_empty_without_tools():
    assert app.build_data({}) == app.empty_data()
    assert app.build_data({"get_portfolio_facts": [{"error": "x"}]}) == app.empty_data()


def test_rates_scenario_in_data():
    rates = {"persona": "robert", "shock_type": "rates", "rates_shock_bp": 100,
             "total": {"impact_pct": -9.1, "lo_pct": -12.0, "hi_pct": -6.0}}
    assert app.build_data({"run_scenario": [rates]})["scenario"] == {
        "subject": "robert", "subject_type": "persona", "shock_type": "rates", "shock_bp": 100,
        "impact_pct": -9.1, "lo_pct": -12.0, "hi_pct": -6.0}


# ---- job processing -------------------------------------------------------------------------

def test_done_path(setup):
    make, item, s3 = setup
    agent = FakeAgent(fake_body())
    make(agent)
    assert app.lambda_handler(event(level="beginner", experiment_id=None), None) == {"batchItemFailures": []}
    kw = agent.calls[0]
    assert kw["agentRuntimeArn"] == ARN
    assert kw["runtimeSessionId"] == "cascade-sess" + "-" * 21
    assert json.loads(kw["payload"]) == {"persona": "robert", "question": "Q?", "level": "beginner",
                                         "experiment_id": None}
    assert s3.puts[0]["Bucket"] == "cascade-s3-bucket" and s3.puts[0]["Key"] == "traces/j1.json"
    assert item["status"] == "DONE" and item["traceKey"] == "traces/j1.json"
    assert item["answer"]["verdict"] == "MYTH"
    assert item["answer"]["headline"] == "Tes obligations n'ont pas protege."
    assert item["answer"]["text"].endswith("Details [1] et [2] puis [1].")
    assert item["answer"]["refusal"] is False and item["answer"]["caveat"]
    assert [c["evidence_id"] for c in item["citations"]] == ["fed-02", "bis-01"]
    assert item["trace"] == TRACE
    assert item["data"]["risk_share"]["rates"] == app.Decimal("0.707")
    assert len(item["toolCalls"]) == 1 and item["claims"]
    assert isinstance(item["durationMs"], int) and item["finishedAt"]


def test_stages_in_order(setup):
    make, item, _ = setup
    make(FakeAgent(fake_body()))
    app.lambda_handler(event(), None)
    assert [s["stage"] for s in item["stages"]] == [
        "queued", "agent_started", "tool:get_portfolio_facts", "tool:run_scenario", "guardrail", "done"]
    assert all(s["t"].endswith("Z") for s in item["stages"])


def test_queued_stage_added_for_old_job_rows(setup):
    make, item, _ = setup
    item.pop("stages")
    make(FakeAgent(fake_body()))
    app.lambda_handler(event(), None)
    assert item["stages"][0]["stage"] == "queued"


def test_level_and_experiment_from_message_reach_the_agent(setup):
    make, item, _ = setup
    agent = FakeAgent(fake_body())
    make(agent)
    app.lambda_handler(event(level="expert", experiment_id="bonds_protect"), None)
    assert json.loads(agent.calls[0]["payload"])["level"] == "expert"
    assert json.loads(agent.calls[0]["payload"])["experiment_id"] == "bonds_protect"


def test_decline_marker_is_a_refusal(setup):
    make, item, _ = setup
    make(FakeAgent(fake_body("[[DECLINE]] Je ne donne pas de conseil. Voici l'historique.")))
    app.lambda_handler(event(), None)
    assert item["answer"]["refusal"] is True and item["answer"]["verdict"] is None
    assert not item["answer"]["text"].startswith("[[")


def test_guardrail_intervention_is_a_refusal(setup):
    make, item, _ = setup
    body = fake_body()
    body["guardrail"] = [{"source": "INPUT", "topics": ["Stock tips"]}]
    make(FakeAgent(body))
    app.lambda_handler(event(), None)
    assert item["answer"]["refusal"] is True
    assert item["guardrail"] == [{"source": "INPUT", "topics": ["Stock tips"]}]


def test_guardrail_absent_by_default(setup):
    make, item, s3 = setup
    make(FakeAgent(fake_body()))
    app.lambda_handler(event(), None)
    assert "guardrail" not in item and item["answer"]["refusal"] is False


def test_data_never_comes_from_answer_text(setup):
    make, item, _ = setup
    body = fake_body("REAL Risk share rates is 0.99 and oil 0.99.")
    body["tool_results"] = {}
    make(FakeAgent(body))
    app.lambda_handler(event(), None)
    assert item["data"] == app.empty_data()


def test_floats_become_decimal(setup):
    make, item, s3 = setup
    make(FakeAgent(fake_body()))
    app.lambda_handler(event(), None)
    assert item["data"]["risk_share"]["rates"] == app.Decimal("0.707")
    assert json.loads(s3.puts[0]["Body"])["response"]["tool_results"]["get_portfolio_facts"][0]["risk_share"]["rates"] == 0.707


def test_plain_text_body(setup):
    make, item, s3 = setup
    make(FakeAgent(b"just text"))
    app.lambda_handler(event(), None)
    assert item["status"] == "DONE" and item["answer"]["text"] == "just text"
    assert item["trace"] == [] and item["citations"] == [] and item["toolCalls"] == []


def test_limits_and_truncation(setup):
    make, item, s3 = setup
    body = {
        "answer_text": "a" * 200_000,
        "trace": [{"step": i, "tool": "f%d" % i, "output_summary": "x" * 1000} for i in range(30)],
        "toolCalls": [{"name": "f%d" % i, "input": {}, "output": ""} for i in range(30)],
    }
    make(FakeAgent(body))
    app.lambda_handler(event(), None)
    assert len(item["toolCalls"]) == 20 and len(item["trace"]) == 20
    assert len(item["trace"][0]["output_summary"]) == app.MAX_SUMMARY
    assert len(item["answer"]["text"]) == app.MAX_ANSWER and item["answer"]["text"].endswith("...")


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
    assert item["stages"][-1]["stage"] == "failed"


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
        def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ExpressionAttributeNames=None, **kw):
            if "ConditionExpression" in kw:
                seen.update(kw, values=ExpressionAttributeValues)
            return super().update_item(Key, UpdateExpression, ExpressionAttributeValues, ExpressionAttributeNames, **kw)

    monkeypatch.setattr(app.time, "time", lambda: 10_000)
    make(FakeAgent(fake_body()), Recording(item))
    app.lambda_handler(event(), None)
    assert "#s = :running AND startedAtEpoch < :stale" in seen["ConditionExpression"]
    assert seen["values"][":stale"] == 10_000 - app.STALE_RUNNING_SECONDS
    assert seen["values"][":now"] == 10_000


# ---- cache ----------------------------------------------------------------------------------

def test_done_job_is_cached_by_persona_experiment_level(setup):
    make, item, _ = setup
    t = make(FakeAgent(fake_body()))
    app.lambda_handler(event(level="beginner", experiment_id="bonds_protect"), None)
    assert t.items["cache#robert#bonds_protect#beginner"] == {
        "jobId": "cache#robert#bonds_protect#beginner", "sourceJobId": "j1", "expiresAt": 5000}


def test_no_cache_without_experiment_id(setup):
    make, item, _ = setup
    t = make(FakeAgent(fake_body()))
    app.lambda_handler(event(), None)
    assert not [k for k in t.items if k.startswith("cache#")]


def test_refusal_is_not_cached(setup):
    make, item, _ = setup
    t = make(FakeAgent(fake_body("[[DECLINE]] No advice. Sorry.")))
    app.lambda_handler(event(experiment_id="bonds_protect"), None)
    assert not [k for k in t.items if k.startswith("cache#")]


def _first_run(make):
    """Run job j1 with experiment_id and return the table that now holds its cache entry."""
    t = make(FakeAgent(fake_body()))
    app.lambda_handler(event(level="beginner", experiment_id="bonds_protect"), None)
    return t


def test_cache_hit_returns_stored_result_without_calling_the_agent(setup):
    make, item, s3 = setup
    t = _first_run(make)
    second = {"jobId": "j2", "status": "PENDING", "question": "Autre?", "persona": "robert",
              "level": "beginner", "sessionId": "s2", "expiresAt": 6000,
              "stages": [{"stage": "queued", "t": "x"}]}
    t.items["j2"] = second
    agent = FakeAgent(fake_body("MINOR different."))
    make(agent, t)
    app.lambda_handler(event(job="j2", level="beginner", experiment_id="bonds_protect"), None)
    assert agent.calls == []
    assert second["status"] == "DONE" and second["cachedFrom"] == "j1"
    assert second["answer"] == item["answer"] and second["data"] == item["data"]
    assert second["citations"] == item["citations"] and second["trace"] == item["trace"]
    assert [s["stage"] for s in second["stages"]] == ["queued", "done"]
    assert len(s3.puts) == 1  # no second agent run, no second trace


def test_cache_is_per_level_and_persona(setup):
    make, item, _ = setup
    t = _first_run(make)
    t.items["j2"] = {"jobId": "j2", "status": "PENDING", "question": "Q", "persona": "robert",
                     "level": "expert", "sessionId": "s2", "expiresAt": 6000, "stages": [{"stage": "queued"}]}
    agent = FakeAgent(fake_body())
    make(agent, t)
    app.lambda_handler(event(job="j2", level="expert", experiment_id="bonds_protect"), None)
    assert len(agent.calls) == 1


def test_cache_ignored_when_source_job_is_gone_or_not_done(setup):
    make, item, _ = setup
    t = _first_run(make)
    item["status"] = "FAILED"
    t.items["j2"] = {"jobId": "j2", "status": "PENDING", "question": "Q", "persona": "robert",
                     "level": "beginner", "sessionId": "s2", "expiresAt": 6000, "stages": [{"stage": "queued"}]}
    agent = FakeAgent(fake_body())
    make(agent, t)
    app.lambda_handler(event(job="j2", level="beginner", experiment_id="bonds_protect"), None)
    assert len(agent.calls) == 1
