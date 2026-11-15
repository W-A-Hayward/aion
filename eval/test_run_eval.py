import importlib.util
import json
import os
import re

_spec = importlib.util.spec_from_file_location("run_eval", os.path.join(os.path.dirname(__file__), "run_eval.py"))
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)

CASES = json.load(open(ev.QUESTIONS))
TOOLS = {"get_portfolio_exposure", "get_asset_sensitivity", "explain_channel", "run_scenario",
         "compare_alternative", "get_validation", "search_evidence"}


def done(answer, tools=(), citations=()):
    return {"status": "DONE", "answer": answer, "toolCalls": [{"name": t} for t in tools], "citations": list(citations)}


def test_questions_file_is_well_formed():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)) >= 12
    for c in CASES:
        assert c["persona"] in ("robert", "amira", "mateo") and c["level"] in ("beginner", "expert")
        assert 0 < len(c["question"]) <= 1000 and c["why"]
        assert set(c["expect"]) <= {"tools_required", "tools_any", "must_include_any", "must_include_all",
                                    "must_not_match", "max_words", "requires_citations"}
        assert set(c["expect"].get("tools_required", [])) <= TOOLS
        for pattern in c["expect"].get("must_not_match", []):
            re.compile(pattern)


def case(cid):
    return next(c for c in CASES if c["id"] == cid)


def test_scoring_catches_advice_and_greek_letters():
    c = case("robert-overall-beginner")
    good = done("For every 10% oil move, your portfolio has moved about 0.3% the other way.", ["get_portfolio_exposure"])
    assert ev.score(c, good) == []
    bad = done("Your β is low, you should sell TLT.", ["get_portfolio_exposure"])
    fails = ev.score(c, bad)
    assert any("β" in f for f in fails) and any("you should sell" in f.lower() for f in fails)


def test_scoring_requires_tools_and_citations():
    c = case("evidence-cited")
    assert any("explain_channel" in f for f in ev.score(c, done("Pipelines.")))
    assert "no citations" in ev.score(c, done("Pipelines.", ["explain_channel"]))
    assert ev.score(c, done("Pipelines.", ["explain_channel"], [{"text": "x"}])) == []


def test_failed_job_is_a_failure():
    assert ev.score(CASES[0], {"status": "FAILED", "error": "boom"}) == ["job ended FAILED: boom"]


def test_word_limit_with_slack():
    c = case("no-oil-forecast")
    assert ev.score(c, done("word " * 200)) == []
    assert ev.score(c, done("word " * 220))
