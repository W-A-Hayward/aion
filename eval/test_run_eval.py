import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import run_eval as ev  # noqa: E402
import report  # noqa: E402


def call(output, name="run_scenario", **inputs):
    return {"name": name, "input": inputs, "output": output}


def test_percent_extraction():
    assert ev.percent_numbers("Down 12.5%, up -3 % and +4 percent; p=0.03") == [12.5, 3.0, 4.0]
    assert ev.percent_numbers("a \u22122.1% move") == [2.1]
    assert ev.percent_numbers("no numbers here, 2021-11") == []


def test_number_in_tool_output_passes():
    calls = [call('{"impact_pct": -12.46, "lo_pct": -20.1}')]
    assert ev.check_numbers("Impact is about 12.5% (range 20.1%).", calls)["pass"]


def test_tolerance_is_0_1_after_rounding():
    calls = [call('{"impact_pct": 5.0}')]
    assert ev.check_numbers("about 5.1%", calls)["pass"]
    assert ev.check_numbers("about 4.9%", calls)["pass"]
    res = ev.check_numbers("about 5.2%", calls)
    assert not res["pass"] and res["flagged"] == [5.2]


def test_sign_is_ignored():
    calls = [call('{"impact_pct": -8.0}')]
    assert ev.check_numbers("a fall of 8%", calls)["pass"]
    assert ev.check_numbers("a gain of +8%", calls)["pass"]


def test_fraction_in_tool_output_matches_percent():
    calls = [call('{"oos_hit_rate": 0.62}', name="get_validation")]
    assert ev.check_numbers("hit rate 62%", calls)["pass"]
    assert not ev.check_numbers("hit rate 72%", calls)["pass"]


def test_invented_number_is_flagged():
    calls = [call('{"impact_pct": 5.0}')]
    res = ev.check_numbers("It could lose 17% and gain 5%.", calls)
    assert not res["pass"] and res["flagged"] == [17.0]


def test_question_and_template_numbers_allowed():
    assert ev.check_numbers("If oil jumps 30%, and for every 10% oil move, with a 95% range.", [],
                            question="What if oil jumps 30%?")["pass"]
    assert not ev.check_numbers("about 40%", [], question="What if oil jumps 30%?")["pass"]


def test_dict_output_and_no_tool_calls():
    assert ev.check_numbers("12%", [call({"x": 12.0})])["pass"]
    assert not ev.check_numbers("12%", [])["pass"]
    assert ev.check_numbers("no percent at all", [])["pass"]


def test_must_call():
    calls = [call("{}", name="get_portfolio_exposure")]
    assert ev.check_must_call(calls, ["get_portfolio_exposure"])["pass"]
    assert ev.check_must_call(calls, ["run_scenario"])["missing"] == ["run_scenario"]


def test_must_mention():
    ans = "RY is not reliably linked to oil. Expect 30% moves? No."
    assert ev.check_must_mention(ans, ["RY.TO", "not reliably linked"])["pass"]
    assert ev.check_must_mention(ans, ["xyz|linked"])["pass"]
    assert ev.check_must_mention(ans, ["30%"])["pass"]
    assert ev.check_must_mention(ans, ["XIU.TO"])["missing"] == ["XIU.TO"]


def test_must_not_word_boundary_and_case():
    assert ev.check_must_not("You should SELL now", ["you should sell"])["found"] == ["you should sell"]
    assert ev.check_must_not("I can't advise whether to sell", ["you should sell"])["pass"]
    assert ev.check_must_not("a sellout", ["sell"])["pass"]
    assert not ev.check_must_not("Sell.", ["sell"])["pass"]


def test_label_check():
    out = json.dumps({"ticker": "RY.TO", "label": "grey"})
    assert ev.check_labels([call(out, name="get_validation", ticker="RY.TO")], {"RY.TO": "grey"})["pass"]
    assert not ev.check_labels([call(out, name="get_validation", ticker="ENB.TO")], {"RY.TO": "grey"})["pass"]
    assert not ev.check_labels([call(out, name="get_validation", ticker="RY.TO")], {"RY.TO": "green"})["pass"]


def test_parse_judge():
    good = {k: {"score": 4, "reason": "ok."} for k in ev.JUDGE_KEYS}
    assert ev.parse_judge("noise " + json.dumps(good))["safety"]["score"] == 4
    bad = dict(good, safety={"score": 7, "reason": "x"})
    try:
        ev.parse_judge(json.dumps(bad))
        assert False
    except ValueError:
        pass


def test_questions_file():
    qs = ev.load_questions()
    assert len(qs) == 24
    for persona in ("robert", "amira", "mateo"):
        for level in ("beginner", "expert"):
            assert sum(1 for q in qs if q["persona"] == persona and q["level"] == level) == 4
    for q in qs:
        assert set(q["expect"]) >= {"must_call", "must_mention", "must_not"}


def test_report_has_24_rows_and_failures():
    recs = []
    for q in ev.load_questions():
        recs.append({"id": q["id"], "persona": q["persona"], "level": q["level"], "question": q["question"],
                     "wallMs": 1000, "pass": q["id"] != "robert-beg-1",
                     "reasons": ["timeout"] if q["id"] == "robert-beg-1" else [],
                     "judge": {"scores": {k: {"score": 4, "reason": "r"} for k in ev.JUDGE_KEYS}}})
    md = report.build_report(recs, "t")
    assert len([l for l in md.splitlines() if "| PASS |" in l or "| FAIL |" in l]) == 24
    assert "robert-beg-1" in md.split("## Failed questions")[1]
    assert report.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 90) == 9
