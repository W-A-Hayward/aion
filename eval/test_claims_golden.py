"""Tests for claims.py, golden.py, the new run_eval checks, consistency and report sections.
Synthetic data only; no AWS calls."""
import importlib.util
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import claims as cl  # noqa: E402
import golden as gd  # noqa: E402
import report  # noqa: E402
import run_eval as ev  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
UNIVERSE = ["ENB.TO", "QQQ", "RY.TO", "SHOP.TO", "SPY", "TLT", "TSLA", "XBB.TO", "XIU.TO", "XOM", "ZST.TO"]


# ----------------------------------------------------------------------------- tolerance

def test_close_absolute_or_relative():
    assert cl.close(0.504, 0.5) and cl.close(0.505, 0.5)
    assert cl.close(0.509, 0.5)            # 1.8% relative
    assert not cl.close(0.52, 0.5)         # 0.02 absolute, 4% relative
    assert cl.close(100.0, 101.9) and not cl.close(100.0, 102.1)
    assert cl.close(-0.003, 0.0) and not cl.close(0.01, 0.0)
    assert not cl.close(None, 1.0) and not cl.close(True, 1.0) and not cl.close(float("nan"), 1.0)


# ----------------------------------------------------------------------------- building claims

EXPOSURE = {"persona": "robert", "holdings": [{"ticker": "TLT", "beta": -0.2}, {"ticker": "RY.TO", "beta": 0.1}],
            "portfolio_beta": {"beta": -0.05}}
SENS = {"ticker": "TLT", "sensitivity": {"beta_simple": -0.2}}
CHANNEL = {"ticker": "TLT", "confidence": {"label": "green"}}
VALID = {"ticker": "TLT", "validation": {"label": "green", "beta_ex2022": -0.1}}
SCEN = {"persona": "robert", "oil_shock_pct": 30, "scenario": [{"impact_pct": -1.5}],
        "holding_impacts": [{"ticker": "TLT", "impact_pct": -5.0}]}
ALT = {"persona": "robert", "holding": "TLT", "alternative": "ZST.TO",
       "comparison": {"beta_holding": -0.2, "beta_alternative": -0.01}}


def test_claims_from_each_tool():
    assert cl.claims_from_result("get_portfolio_exposure", {"persona": "robert"}, EXPOSURE) == [
        {"ticker": "TLT", "beta": -0.2}, {"ticker": "RY.TO", "beta": 0.1}, {"persona": "robert", "beta": -0.05}]
    assert cl.claims_from_result("get_asset_sensitivity", {}, SENS) == [{"ticker": "TLT", "beta": -0.2}]
    assert cl.claims_from_result("explain_channel", {}, CHANNEL) == [{"ticker": "TLT", "label": "green"}]
    assert cl.claims_from_result("get_validation", {}, VALID) == [{"ticker": "TLT", "label": "green"}]
    assert cl.claims_from_result("run_scenario", {}, SCEN) == [
        {"persona": "robert", "impact_pct": -1.5, "shock_pct": 30},
        {"ticker": "TLT", "impact_pct": -5.0, "shock_pct": 30}]
    assert cl.claims_from_result("compare_alternative", {}, ALT) == [
        {"ticker": "TLT", "beta": -0.2}, {"ticker": "ZST.TO", "beta": -0.01}]


def test_errors_and_missing_values_give_no_claims():
    assert cl.claims_from_result("explain_channel", {"ticker": "X"}, {"error": "unknown ticker"}) == []
    assert cl.claims_from_result("explain_channel", {"ticker": "RY.TO"}, {"ticker": "RY.TO", "confidence": None}) == []
    assert cl.claims_from_result("search_evidence", {}, [{"text": "x"}]) == []


def test_verdict_is_picked_up_when_a_tool_returns_one():
    out = cl.claims_from_result("explain_channel", {}, {"ticker": "TLT", "confidence": {"label": "green"},
                                                         "materiality": {"verdict": "material"}})
    assert {"ticker": "TLT", "verdict": "material"} in out


def test_dedupe_and_rebuild_from_tool_calls():
    calls = [
        {"name": "explain_channel", "input": {"ticker": "TLT"}, "output": json.dumps(CHANNEL)},
        {"name": "get_validation", "input": {"ticker": "TLT"}, "output": json.dumps(VALID)},
        {"name": "get_asset_sensitivity", "input": {"ticker": "TLT"}, "output": SENS},
        {"name": "run_scenario", "input": {}, "output": '{"scenario": [{"impact_pct": 1.0...[truncated]'},
    ]
    out, unparsed = cl.claims_from_tool_calls(calls)
    assert out == [{"ticker": "TLT", "label": "green"}, {"ticker": "TLT", "beta": -0.2}]
    assert unparsed == 1


def _load_agent():
    """Import agent/agent.py, stubbing the runtime packages when they are not installed."""
    app = type("App", (), {"entrypoint": lambda self, fn: fn, "run": lambda self: None})
    for name, attrs in (("bedrock_agentcore", {}), ("bedrock_agentcore.runtime", {"BedrockAgentCoreApp": app}),
                        ("strands", {"tool": lambda fn: fn, "Agent": object}),
                        ("strands.models", {"BedrockModel": object})):
        try:
            __import__(name)
        except ImportError:
            mod = types.ModuleType(name)
            mod.__dict__.update(attrs)
            sys.modules[name] = mod
    path = os.path.join(HERE, "..", "agent", "agent.py")
    spec = importlib.util.spec_from_file_location("cascade_agent_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agent_and_eval_build_the_same_claims():
    agent = _load_agent()
    cases = [("get_portfolio_exposure", {"persona": "robert"}, EXPOSURE), ("get_asset_sensitivity", {}, SENS),
             ("explain_channel", {}, CHANNEL), ("get_validation", {}, VALID), ("run_scenario", {}, SCEN),
             ("compare_alternative", {}, ALT), ("explain_channel", {}, {"error": "x"}),
             ("explain_channel", {}, {"ticker": "TLT", "confidence": {"label": "grey"}, "verdict": "immaterial"})]
    for name, params, result in cases:
        assert agent.claims_from_result(name, params, result) == cl.claims_from_result(name, params, result), name


def test_agent_records_claims_deduplicated():
    agent = _load_agent()
    agent._claims.clear()
    agent._record_claims("explain_channel", {"ticker": "TLT"}, CHANNEL)
    agent._record_claims("get_validation", {"ticker": "TLT"}, VALID)
    agent._record_claims("explain_channel", {"ticker": "TLT"}, {"error": "tool call failed", "allowed": []})
    assert agent._claims == [{"ticker": "TLT", "label": "green"}]


# ----------------------------------------------------------------------------- claims vs golden

EXPECTED = {"persona": "robert", "labels": {"TLT": "green", "RY.TO": "grey"}, "betas": {"TLT": -0.2, "RY.TO": 0.1},
            "portfolio_beta": {"beta": -0.05, "lo": -0.1, "hi": 0.0}, "verdicts": {"TLT": "material"},
            "impacts": {"persona|robert|30": -1.5, "ticker|TLT|30": -5.0}}


def test_check_claims_pass():
    claims = [{"ticker": "TLT", "label": "green"}, {"ticker": "TLT", "beta": -0.2004},
              {"persona": "robert", "beta": -0.0504}, {"ticker": "TLT", "verdict": "material"},
              {"persona": "robert", "impact_pct": -1.52, "shock_pct": 30}]
    res = cl.check_claims(claims, EXPECTED)
    assert res["pass"] and res["checked"] == 5 and res["unchecked"] == []


def test_labels_must_match_exactly():
    res = cl.check_claims([{"ticker": "RY.TO", "label": "yellow"}], EXPECTED)
    assert not res["pass"] and "golden 'grey'" in res["problems"][0]
    assert not cl.check_claims([{"ticker": "RY.TO", "label": "Grey"}], EXPECTED)["pass"]


def test_number_and_verdict_mismatches_fail():
    assert not cl.check_claims([{"ticker": "TLT", "beta": -0.25}], EXPECTED)["pass"]
    assert not cl.check_claims([{"ticker": "TLT", "verdict": "immaterial"}], EXPECTED)["pass"]
    assert not cl.check_claims([{"ticker": "TLT", "impact_pct": -6.0, "shock_pct": 30}], EXPECTED)["pass"]


def test_claim_without_golden_value_is_unchecked_not_failed():
    claims = [{"ticker": "ENB.TO", "beta": 0.5}, {"ticker": "TLT", "impact_pct": -1.0, "shock_pct": -15},
              {"persona": "amira", "beta": 0.9}, {"ticker": "RY.TO", "verdict": "x"}]
    res = cl.check_claims(claims, EXPECTED)
    assert res["pass"] and res["checked"] == 0 and len(res["unchecked"]) == 4


# ----------------------------------------------------------------------------- agreement and stability

def test_agreement_counts_shared_tickers_only():
    a = [{"ticker": "TLT", "label": "green"}, {"ticker": "RY.TO", "label": "grey"}, {"ticker": "XOM", "label": "green"}]
    b = [{"ticker": "TLT", "label": "green"}, {"ticker": "RY.TO", "label": "yellow"}, {"ticker": "ENB.TO", "label": "x"}]
    res = cl.agreement(a, b)
    assert res["label"] == {"agree": 1, "compared": 2, "disagree": ["RY.TO"]}
    assert res["verdict"] == {"agree": 0, "compared": 0, "disagree": []}


def test_stability_identical_runs():
    run = [{"ticker": "TLT", "label": "green"}, {"ticker": "TLT", "beta": -0.2},
           {"persona": "robert", "impact_pct": -1.5, "shock_pct": 30}]
    st = cl.stability([run, list(run), list(run)])
    assert st["label"]["stable"] == 1 and st["numbers"]["stable"] == 2 and st["numbers"]["max_spread"] == 0


def test_stability_flags_changed_missing_and_drifting_values():
    r1 = [{"ticker": "TLT", "label": "green"}, {"ticker": "RY.TO", "label": "grey"}, {"ticker": "TLT", "beta": -0.20}]
    r2 = [{"ticker": "TLT", "label": "yellow"}, {"ticker": "RY.TO", "label": "grey"}, {"ticker": "TLT", "beta": -0.30}]
    r3 = [{"ticker": "TLT", "label": "green"}, {"ticker": "TLT", "beta": -0.20}]
    st = cl.stability([r1, r2, r3])
    assert st["label"]["unstable"] == ["TLT"] and st["label"]["partial"] == ["RY.TO"] and st["label"]["stable"] == 0
    assert st["numbers"]["unstable"] == ["ticker|TLT|beta|"] and abs(st["numbers"]["max_spread"] - 0.1) < 1e-9


# ----------------------------------------------------------------------------- golden

def _tables(materiality=None):
    return {
        "sensitivities": [{"ticker": t, "beta_simple": 0.1 * i} for i, t in enumerate(UNIVERSE)],
        "confidence": [{"ticker": t, "label": "grey"} for t in UNIVERSE if t not in ("ZST.TO", "TLT")] + [
            {"ticker": "TLT", "label": "green"}],
        "portfolio_beta": [{"persona": "robert", "beta": -0.05, "lo": -0.1, "hi": 0.0},
                           {"persona": "amira", "beta": 0.4, "lo": 0.2, "hi": 0.6}],
        "persona_holdings": [{"persona": "robert", "ticker": "TLT", "weight": 0.3},
                             {"persona": "robert", "ticker": "RY.TO", "weight": 0.7},
                             {"persona": "amira", "ticker": "QQQ", "weight": 1.0}],
        "alternatives": [{"persona": "robert", "holding": "TLT", "alternative": "ZST.TO"}],
        "scenarios": [{"subject": "robert", "subject_type": "persona", "shock_pct": 30.0, "impact_pct": -1.5},
                      {"subject": "TLT", "subject_type": "ticker", "shock_pct": -15.0, "impact_pct": 2.0},
                      {"subject": "QQQ", "subject_type": "ticker", "shock_pct": 30.0, "impact_pct": 3.0}],
        "evidence_urls": [{"source_url": "https://a.example/x"}, {"source_url": "https://b.example/y"}],
        "materiality": materiality,
    }


QUESTIONS = [
    {"id": "robert-beg-1", "persona": "robert", "level": "beginner", "question": "Is RY secretly an oil stock?",
     "expect": {"must_mention": ["RY.TO"], "expected_label": {"RY.TO": "grey"}}},
    {"id": "robert-exp-9", "persona": "robert", "level": "expert", "question": "What about Tesla?",
     "expect": {"must_mention": ["TSLA|Tesla"]}},
]


def test_build_golden_values():
    g = gd.build_golden(QUESTIONS, _tables(), generated_at="t")
    q = g["questions"]["robert-beg-1"]
    assert q["allowed_tickers"] == ["RY.TO", "TLT", "ZST.TO"]
    assert q["alternatives"] == [["TLT", "ZST.TO"]]
    assert q["labels"]["TLT"] == "green" and q["labels"]["RY.TO"] == "grey" and "ZST.TO" not in q["labels"]
    assert q["betas"]["TLT"] == 0.1 * UNIVERSE.index("TLT")
    assert q["portfolio_beta"] == {"beta": -0.05, "lo": -0.1, "hi": 0.0}
    assert q["impacts"] == {"persona|robert|30": -1.5, "ticker|TLT|-15": 2.0}
    assert q["verdicts"] == {} and g["materiality"] == "table materiality does not exist"
    assert g["evidence_urls"] == ["https://a.example/x", "https://b.example/y"]
    assert g["universe"] == UNIVERSE


def test_golden_includes_tickers_named_in_the_question_and_materiality_verdicts():
    mat = [{"subject": "TLT", "verdict": "material"}, {"subject": "robert", "verdict": "not material"},
           {"subject": "SPY", "verdict": "x"}]
    g = gd.build_golden(QUESTIONS, _tables(mat), generated_at="t")
    q = g["questions"]["robert-exp-9"]
    assert "TSLA" in q["tickers"] and "TSLA" not in q["allowed_tickers"]
    assert q["verdicts"] == {"TLT": "material", "robert": "not material"}
    assert g["materiality"] == "used"


def test_convert_athena_text():
    assert gd.convert("0.5") == 0.5 and gd.convert("-3") == -3.0 and gd.convert("NaN") is None
    assert gd.convert("") is None and gd.convert(None) is None and gd.convert("XOM") == "XOM"


class _FakeAthena:
    def __init__(self):
        self.sql = []

    def start_query_execution(self, QueryString, **kwargs):
        self.sql.append((QueryString, kwargs))
        return {"QueryExecutionId": "q"}

    def get_query_execution(self, QueryExecutionId):
        return {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}

    def get_query_results(self, QueryExecutionId, **kwargs):
        rows = [{"Data": [{"VarCharValue": "ticker"}, {"VarCharValue": "label"}]},
                {"Data": [{"VarCharValue": "TLT"}, {"VarCharValue": "green"}]}]
        return {"ResultSet": {"Rows": rows}}


def test_run_query_uses_workgroup_and_database():
    fake = _FakeAthena()
    assert gd.run_query(fake, "SELECT 1") == [{"ticker": "TLT", "label": "green"}]
    kwargs = fake.sql[0][1]
    assert kwargs["WorkGroup"] == "cascade" and kwargs["QueryExecutionContext"] == {"Database": "cascade"}


# ----------------------------------------------------------------------------- run_eval checks

def test_find_tickers_case_sensitive_with_bare_roots():
    assert ev.find_tickers("RY and XIU.TO, not ry or SPYDER", UNIVERSE) == {"RY.TO", "XIU.TO"}
    assert ev.find_tickers("TLT's duration", UNIVERSE) == {"TLT"}


def test_tickers_must_belong_to_persona_or_question():
    allowed = ["TLT", "RY.TO", "ZST.TO"]
    assert ev.check_tickers("TLT and RY hold up", "Is RY an oil stock?", allowed, UNIVERSE)["pass"]
    res = ev.check_tickers("TLT, and also SPY.", "Is RY an oil stock?", allowed, UNIVERSE)
    assert not res["pass"] and res["problems"] == ["SPY"]
    assert ev.check_tickers("TSLA has a beta", "What about TSLA?", allowed, UNIVERSE)["pass"]
    # looked up by the agent: tool argument or claim subject
    calls = [{"name": "get_asset_sensitivity", "input": {"ticker": "SPY"}}]
    assert ev.check_tickers("SPY moves", "Compare it", allowed, UNIVERSE, calls)["pass"]
    assert ev.check_tickers("SPY moves", "Compare it", allowed, UNIVERSE, None, [{"ticker": "SPY", "beta": 1}])["pass"]
    assert not ev.check_tickers("SPY moves", "Compare it", allowed, UNIVERSE, [{"name": "x", "input": {"ticker": "XOM"}}])["pass"]


def test_tool_args_match_persona_and_pairs():
    calls = [{"name": "get_portfolio_exposure", "input": {"persona": "Robert"}},
             {"name": "compare_alternative", "input": {"persona": "robert", "holding": "tlt", "alternative": "ZST.TO"}}]
    assert ev.check_tool_args(calls, "robert", [["TLT", "ZST.TO"]])["pass"]
    bad = calls + [{"name": "run_scenario", "input": {"persona": "amira", "oil_shock_pct": "30"}},
                   {"name": "compare_alternative", "input": {"persona": "robert", "holding": "XBB.TO", "alternative": "XESG.TO"}}]
    res = ev.check_tool_args(bad, "robert", [["TLT", "ZST.TO"]])
    assert not res["pass"] and len(res["problems"]) == 2


CITES = [{"text": "Pipeline tariffs are\n regulated and   largely pass through oil price changes.",
          "source_url": "https://a.example/x"}]


def test_quotes_must_be_substrings_of_a_citation():
    ok = 'The filing says "regulated and largely pass through oil price changes" for ENB.TO.'
    assert ev.check_quotes(ok, CITES)["pass"]
    assert ev.check_quotes('It says "regulated ... oil price changes".', CITES)["pass"]
    bad = 'The filing says "tariffs are fully immune to the oil price".'
    res = ev.check_quotes(bad, CITES)
    assert not res["pass"] and res["problems"]
    assert ev.check_quotes('Labelled "not reliably linked" here.', CITES)["pass"]  # under 4 words: not a citation
    assert not ev.check_quotes(ok, [])["pass"]


def test_source_urls_must_exist_in_evidence():
    known = ["https://a.example/x", "https://b.example/y"]
    assert ev.check_sources("See https://b.example/y.", CITES, known)["pass"]
    res = ev.check_sources("See https://c.example/z", CITES + [{"source_url": "s3://kb/doc"}], known)
    assert not res["pass"] and res["problems"] == ["https://c.example/z", "s3://kb/doc"]


def _golden():
    g = gd.build_golden(QUESTIONS, _tables(), generated_at="t")
    return g


def test_run_checks_with_golden_and_reasons():
    q = dict(QUESTIONS[0], expect=dict(QUESTIONS[0]["expect"], must_call=[], must_not=[]))
    calls = [{"name": "explain_channel", "input": {"ticker": "RY.TO"},
              "output": json.dumps({"ticker": "RY.TO", "confidence": {"label": "grey"}})}]
    good = ev.run_checks(q, "RY.TO is not reliably linked.", calls, [], [{"ticker": "RY.TO", "label": "grey"}], _golden())
    assert all(c["pass"] for c in good.values()), good
    bad = ev.run_checks(q, "RY.TO and SPY.", calls, [], [{"ticker": "RY.TO", "label": "green"}], _golden())
    assert not bad["claims"]["pass"] and not bad["tickers"]["pass"]
    reasons = ev.check_reasons(bad)
    assert any("claim differs" in r for r in reasons) and any("ticker outside" in r for r in reasons)


def test_run_checks_without_golden_keeps_old_behaviour():
    checks = ev.run_checks(QUESTIONS[0], "RY.TO", [])
    assert not {"claims", "tickers", "tool_args", "quotes", "sources"} & set(checks)


def test_job_claims_prefers_agent_claims_then_falls_back():
    assert ev.job_claims({"claims": [{"ticker": "TLT", "label": "green"}] * 2}) == (
        [{"ticker": "TLT", "label": "green"}], "agent")
    body = {"toolCalls": [{"name": "explain_channel", "input": {}, "output": json.dumps(CHANNEL)}]}
    assert ev.job_claims(body) == ([{"ticker": "TLT", "label": "green"}], "toolCalls")


# ----------------------------------------------------------------------------- consistency and report

def test_consistency_file_is_valid():
    qs = ev.load_questions()
    config = ev.load_consistency(qs)
    assert len(config["paraphrases"]) == 6 and len(config["repeats"]["ids"]) == 3 and config["repeats"]["n"] == 3
    jobs = ev.consistency_jobs(config, qs)
    assert len(jobs) == 6 * 2 + 3 * 3
    by_id = {q["id"]: q for q in qs}
    for j in jobs:
        base = by_id[j["id"]]
        assert j["question"]["persona"] == base["persona"]
        if j["kind"] == "other_level":
            assert j["question"]["level"] != base["level"] and j["question"]["question"] == base["question"]
        else:
            assert j["question"]["level"] == base["level"]
        if j["kind"] == "paraphrase":
            assert j["question"]["question"] != base["question"]


def _variant(kind, qid, claims, status="DONE", run=0):
    return {"kind": kind, "id": qid, "run": run, "level": "beginner", "question": "q", "status": status,
            "claims": claims, "claimsSource": "agent", "jobId": "j", "error": None if status == "DONE" else "timeout"}


def test_summarize_consistency():
    base = [{"id": "a", "status": "DONE", "claims": [{"ticker": "TLT", "label": "green"}]}]
    same = [{"ticker": "TLT", "label": "green"}]
    variants = [_variant("paraphrase", "a", same), _variant("other_level", "a", [{"ticker": "TLT", "label": "yellow"}]),
                _variant("repeat", "a", same, run=1), _variant("repeat", "a", same, run=2),
                _variant("repeat", "a", [], status="TIMEOUT", run=3)]
    s = ev.summarize_consistency(base, variants)
    assert s["pairs"][0]["label"]["agree"] == 1 and s["pairs"][1]["label"]["disagree"] == ["TLT"]
    rep = s["repeats"][0]
    assert rep["requested"] == 3 and rep["runs"] == 2 and rep["stability"]["label"]["stable"] == 1


def test_report_sections_and_content():
    recs = []
    for q in ev.load_questions():
        recs.append({"id": q["id"], "persona": q["persona"], "level": q["level"], "question": q["question"],
                     "wallMs": 1000, "pass": True, "reasons": [], "claimsSource": "agent",
                     "checks": {"claims": {"pass": q["id"] != "robert-beg-1", "checked": 3,
                                           "problems": ["ticker RY.TO label='green', golden 'grey'"], "unchecked": ["x"]},
                                "quotes": {"pass": True, "problems": []},
                                "must_call": {"pass": True, "missing": []}},
                     "judge": {"scores": {k: {"score": 4, "reason": "r"} for k in ev.JUDGE_KEYS}}})
    base = [{"id": "a", "status": "DONE", "claims": [{"ticker": "TLT", "label": "green"}]}]
    variants = [_variant("paraphrase", "a", [{"ticker": "TLT", "label": "green"}]),
                _variant("repeat", "a", [{"ticker": "TLT", "label": "green"}], run=1)]
    md = report.build_report(recs, "t", {"summary": ev.summarize_consistency(base, variants), "variants": variants})
    order = [md.index(h) for h in ("## Factual accuracy", "## Faithfulness", "## Trajectory", "## Consistency", "## Judge")]
    assert order == sorted(order)
    facts = md.split("## Factual accuracy")[1].split("## Faithfulness")[0]
    assert "Claims match golden | 23 | 24" in facts and "robert-beg-1" in facts and "golden 'grey'" in facts
    assert "Claim values checked: 72. Unchecked (no golden value): 24. Claims source: agent 24." in facts
    assert "Overall label agreement: 1/1 (100%)" in md.split("## Consistency")[1]
    assert len([l for l in md.splitlines() if "| PASS |" in l or "| FAIL |" in l]) == 24
    assert "No consistency results" in report.build_report(recs, "t")


def test_claims_check_fails_when_tools_were_required_but_nothing_was_checked():
    q = dict(QUESTIONS[0], expect={"must_call": ["explain_channel"], "must_mention": [], "must_not": []})
    g = _golden()
    for claims in ([], [{"ticker": "ENB.TO", "beta": 0.5}]):   # none, or only values with no golden value
        res = ev.run_checks(q, "RY.TO", [], [], claims, g)["claims"]
        assert not res["pass"] and "no claim could be checked" in res["problems"][-1]
    ok = ev.run_checks(q, "RY.TO", [], [], [{"ticker": "RY.TO", "label": "grey"}], g)["claims"]
    assert ok["pass"]
    # a question that needs no tools is not failed for having no claims
    q0 = dict(q, expect={"must_call": [], "must_mention": [], "must_not": []})
    assert ev.run_checks(q0, "RY.TO", [], [], [], g)["claims"]["pass"]


# ----------------------------------------------------------------------------- evaluate() and consistency flow

def _body(label, answer="RY.TO is not reliably linked."):
    out = json.dumps({"ticker": "RY.TO", "confidence": {"label": label}})
    return {"status": "DONE", "jobId": "j1", "answer": answer, "durationMs": 5,
            "toolCalls": [{"name": "explain_channel", "input": {"ticker": "RY.TO", "persona": "robert"}, "output": out}],
            "citations": [], "claims": [{"ticker": "RY.TO", "label": label}]}


def _judge_ok(*a, **k):
    return {"scores": {key: {"score": 5, "reason": "ok"} for key in ev.JUDGE_KEYS}}


def test_evaluate_wires_claims_golden_and_pass(monkeypatch):
    q = dict(QUESTIONS[0], expect={"must_call": ["explain_channel"], "must_mention": ["RY.TO"], "must_not": [],
                                   "expected_label": {"RY.TO": "grey"}})
    monkeypatch.setattr(ev, "judge", _judge_ok)
    monkeypatch.setattr(ev, "run_job", lambda base, question: _body("grey"))
    rec = ev.evaluate(q, "http://api", "m", _golden())
    assert rec["pass"], rec["reasons"]
    assert rec["claimsSource"] == "agent" and rec["claims"] == [{"ticker": "RY.TO", "label": "grey"}]
    assert rec["checks"]["claims"]["checked"] == 1 and rec["checks"]["tool_args"]["pass"]

    monkeypatch.setattr(ev, "run_job", lambda base, question: _body("green"))
    bad = ev.evaluate(q, "http://api", "m", _golden())
    assert not bad["pass"] and any("claim differs from golden" in r for r in bad["reasons"])


def test_evaluate_records_job_errors_and_skips_golden_checks_without_golden(monkeypatch):
    def boom(base, question):
        raise ev.JobError("timeout: job x not DONE")
    monkeypatch.setattr(ev, "run_job", boom)
    rec = ev.evaluate(QUESTIONS[0], "http://api", "m", _golden())
    assert rec["status"] == "TIMEOUT" and not rec["pass"] and rec["checks"] is None
    monkeypatch.setattr(ev, "judge", _judge_ok)
    monkeypatch.setattr(ev, "run_job", lambda base, question: _body("grey"))
    rec = ev.evaluate(QUESTIONS[0], "http://api", "m", None)
    assert "claims" not in rec["checks"]


def test_consistency_flow_end_to_end_with_fake_api(monkeypatch):
    labels = {"robert-beg-1": "grey"}

    def fake_job(base, question):
        # the other level answers differently, to prove disagreements are reported
        return _body("yellow" if question["level"] == "expert" else labels["robert-beg-1"])
    monkeypatch.setattr(ev, "run_job", fake_job)
    qs = [dict(QUESTIONS[0], expect={})]
    config = {"paraphrases": [{"id": "robert-beg-1", "question": "Is my RY tied to oil?"}],
              "repeats": {"ids": ["robert-beg-1"], "n": 3}}
    base = [{"id": "robert-beg-1", "status": "DONE", "claims": [{"ticker": "RY.TO", "label": "grey"}]}]
    variants = [ev.run_consistency_job(j, "http://api") for j in ev.consistency_jobs(config, qs)]
    s = ev.summarize_consistency(base, variants)
    by_kind = {p["kind"]: p for p in s["pairs"]}
    assert by_kind["paraphrase"]["label"]["disagree"] == [] and by_kind["other_level"]["label"]["disagree"] == ["RY.TO"]
    assert s["repeats"][0]["runs"] == 3 and s["repeats"][0]["stability"]["label"]["stable"] == 1
