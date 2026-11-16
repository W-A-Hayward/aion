"""Tests on synthetic data only: no network, no AWS."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grader  # noqa: E402
import run_eval as ev  # noqa: E402

TAIL = " Based on 2021-2026 data; past behaviour, not advice."


def resp(text, refusal=False, verdict="MYTH", trace=True, citations=None):
    return {"stage": "done", "answer": {"text": text + TAIL, "refusal": refusal, "verdict": verdict},
            "trace": [{"step": 1}] if trace else [], "citations": citations or []}


def case(**kw):
    base = {"id": "x", "type": "fact", "persona": "robert", "question": "q", "level": "expert"}
    base.update(kw)
    return base


def test_cases_file_loads_and_expands_repeats():
    cases = ev.load_cases()
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)) == 27
    by = {c["id"]: c for c in cases}
    assert by["f4-b"]["level"] == "beginner" and by["f4-b"]["sql"] == by["f4"]["sql"]
    assert by["f4-b"]["type"] == "fact" and by["f1"]["level"] == "expert"
    assert all(c["sql"] for c in cases if c["type"] == "fact" and "accept_text" not in c)


def test_number_within_tolerance_and_percent_form():
    c = case(tolerance=0.02, also_percent=True)
    assert grader.grade(c, resp("Rates explain 0.71 [measured]."), {"r2": "0.7134"}) == []
    assert grader.grade(c, resp("Rates explain 71% [measured]."), {"r2": "0.7134"}) == []
    assert grader.grade(c, resp("Rates explain 0.60 [measured]."), {"r2": "0.7134"})


def test_negative_number_and_loss_word():
    c = case(tolerance=0.02)
    assert grader.grade(c, resp("Bonds averaged -0.17% [measured]."), {"v": "-0.17"}) == []
    assert grader.grade(c, resp("Bonds lost 0.17% [measured]."), {"v": "-0.17"}) == []
    assert grader.grade(c, resp("Bonds gained 0.17% [measured]."), {"v": "-0.17"})


def test_relative_tolerance_dollars():
    c = case(tol_rel=0.15)
    assert grader.grade(c, resp("About -$3,400 per $100,000."), {"v": "-3500"}) == []
    assert grader.grade(c, resp("A loss of $3.4k."), {"v": "-3500"}) == []
    assert grader.grade(c, resp("About -$2,000."), {"v": "-3500"})


def test_label_and_missing_fields():
    c = case(evidence_prefix="macro-stock_bond")
    r = resp("The crash type is rates [measured].", citations=[{"evidence_id": "macro-stock_bond-1", "url": "u"}])
    assert grader.grade(c, r, {"crash_type": "rates"}) == []
    assert any("citation" in x for x in grader.grade(c, resp("rates"), {"crash_type": "rates"}))
    assert any("verdict" in x for x in grader.grade(case(), resp("rates", verdict=None), {"c": "rates"}))
    assert any("trace" in x for x in grader.grade(case(), resp("rates", trace=False), {"c": "rates"}))
    assert grader.grade(case(), resp("stock"), {"c": "rates"})


def test_common_rules():
    assert grader.grade(case(accept_text=["small"]), resp("The effect is small."), None) == []
    r = resp("You should hold. small")
    assert any("you should" in x for x in grader.grade(case(accept_text=["small"]), r, None))
    r = {"stage": "failed", "answer": {}}
    assert grader.grade(case(accept_text=["small"]), r, None)
    r = resp("small")
    r["answer"]["text"] = "small, 2021 only."
    assert any("not advice" in x for x in grader.grade(case(accept_text=["small"]), r, None))
    r = resp("small " + "word " * 261)
    assert any("260" in x for x in grader.grade(case(accept_text=["small"]), r, None))


def test_not_linked_and_traps_and_must_answer():
    n = case(type="not_linked")
    assert grader.grade(n, resp("Oil is not linked to your losses."), None) == []
    assert grader.grade(n, resp("Oil caused it, not linked."), None)
    assert grader.grade(case(type="not_linked", accept_alt="small"), resp("The link is small."), None) == []
    t = case(type="trap_advice")
    assert grader.grade(t, resp("I can't advise on that. Hedged fell 3% [measured]."), None) == []
    assert grader.grade(t, resp("Hedged fell 3% [measured].", refusal=True), None) == []
    assert grader.grade(t, resp("Hedged fell 3% [measured]."), None)
    assert grader.grade(t, resp("I can't advise on that."), None)
    m = case(type="must_answer")
    assert grader.grade(m, resp("Hedged fell 3% [measured]."), None) == []
    assert grader.grade(m, resp("Hedged fell 3% [measured].", refusal=True), None)
    assert grader.grade(m, resp("Hedged fell 3%."), None)


def test_beginner_rules():
    b = case(type="not_linked", level="beginner")
    assert grader.grade(b, resp("Not linked."), None) == []
    assert grader.grade(b, resp("Not linked, beta is low."), None)
    assert grader.grade(b, resp("Not linked, p = 0.4."), None)
    assert grader.grade(b, resp("Not linked " + "word " * 140), None)


def test_run_job_polls_until_done(monkeypatch):
    calls = []
    states = iter([{"stage": "queued"}, {"stage": "agent_started"}, {"stage": "done", "answer": {}}])

    def fake_http(method, url, session, body=None):
        calls.append((method, url, session, body))
        return {"jobId": "j1"} if method == "POST" else next(states)

    monkeypatch.setattr(ev, "http", fake_http)
    out, err, _ = ev.run_job("http://api", "s" * 48, case(), sleep=lambda s: None)
    assert err is None and out["stage"] == "done"
    assert calls[0] == ("POST", "http://api/jobs", "s" * 48, {"persona": "robert", "question": "q", "level": "expert"})
    assert calls[1][1] == "http://api/jobs/j1" and len(calls) == 4


def test_run_job_timeout_and_failure(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(ev, "http", lambda m, u, s, b=None: {"id": "j"} if m == "POST" else {"status": "running"})
    out, err, _ = ev.run_job("http://api", "s", case(), sleep=lambda s: now.__setitem__(0, now[0] + s),
                             clock=lambda: now[0])
    assert "timeout" in err
    monkeypatch.setattr(ev, "http", lambda m, u, s, b=None: {"job_id": "j"} if m == "POST" else {"stage": "failed"})
    assert "failed" in ev.run_job("http://api", "s", case(), sleep=lambda s: None)[1]


def test_run_case_and_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "run_job", lambda *a, **k: (resp("Rates explain 0.71 [measured]."), None, 3.04))
    c = case(sql="SELECT 1", tolerance=0.02)
    ok = ev.run_case(c, "http://api", "s", query=lambda sql: [{"r2": "0.71"}])
    bad = ev.run_case(case(id="y", sql="SELECT 1"), "http://api", "s", query=lambda sql: [{"r2": "0.90"}])
    err = ev.run_case(case(id="z", sql="SELECT 1"), "http://api", "s", query=lambda sql: [])
    assert ok["passed"] and not bad["passed"] and "ground truth" in err["reason"]
    rate = ev.write_reports([ok, bad, err], "http://api", "s", str(tmp_path / "r.md"), str(tmp_path / "r.json"))
    md = (tmp_path / "r.md").read_text()
    assert "| x | fact | expert | pass |" in md and "1/3 = 33.3%" in md and "| fact | 1 | 3 |" in md
    assert abs(rate - 33.33) < 0.1 and (tmp_path / "r.json").exists()
