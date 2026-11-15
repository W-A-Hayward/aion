import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import app  # noqa: E402


class FakeAthena:
    def __init__(self):
        self.sql = []
        self.last = None

    def start_query_execution(self, QueryString, **kw):
        self.sql.append(QueryString)
        self.last = QueryString
        return {"QueryExecutionId": "q%d" % len(self.sql)}

    def get_query_execution(self, QueryExecutionId):
        return {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}

    def get_query_results(self, QueryExecutionId, NextToken=None):
        s = self.last
        if "max(week)" in s:
            h, rows = ["as_of"], [["2026-11-13"]]
        elif "FROM rolling" in s:
            h = ["week", "beta_52w"]
            rows = [["2026-11-%02d" % d, "0.%d" % d] for d in (13, 6, 2, 1)]
        elif "FROM sensitivities s" in s:
            h = ["beta_ex2022", "lo_ex2022", "hi_ex2022", "oos_hit_rate", "oos_n", "beta_up",
                 "beta_down", "label", "reason_text"]
            rows = [["0.12345", "0.1", "0.2", "0.6", "100", "0.3", "0.2", "green", "ok"]]
        elif "FROM sensitivities" in s:
            h, rows = ["ticker", "beta_simple"], [["TLT", "-0.123456"]]
        elif "FROM confidence" in s:
            h, rows = ["ticker", "channel", "label"], [["ZST.TO", "rates", "grey"]]
        elif "FROM chain_reconciliation" in s:
            h, rows = ["ticker", "chain", "beta_direct"], [["ZST.TO", "oil>ca2y>ZST.TO", "0.1"]]
        elif "FROM links" in s:
            h = ["link_id", "beta"]
            rows = [["oil>ca2y", "1"], ["ca2y>ZST.TO", "2"], ["oil>us10y", "3"]]
        elif "FROM duration_check" in s:
            h, rows = ["ticker", "duration_years"], [["ZST.TO", "0.4"]]
        elif "FROM evidence" in s:
            h = ["evidence_id", "ticker", "channel", "excerpt"]
            rows = [["e1", "macro", "rates", "x" * 5000]] if "'macro'" in s else []
        elif "FROM portfolio_beta" in s:
            h, rows = ["beta", "lo", "hi"], [["0.2", "0.1", "0.3"]]
        elif "FROM persona_holdings" in s or "FROM portfolio_exposure" in s:
            h = ["ticker", "weight", "beta", "lo", "hi", "contribution"]
            rows = [["TLT", "0.3", "-0.2", "-0.3", "-0.1", "-0.06"]]
        elif "FROM scenarios" in s:
            h, rows = ["subject", "shock_pct", "impact_pct"], [["robert", "30", "-5"]]
        elif "FROM alternatives" in s:
            h, rows = ["persona", "holding", "alternative"], [["robert", "TLT", "ZST.TO"]]
        else:
            raise AssertionError(s)
        data = [{"Data": [{"VarCharValue": c} for c in h]}]
        data += [{"Data": [{"VarCharValue": c} for c in r]} for r in rows]
        return {"ResultSet": {"Rows": data}}


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    f = FakeAthena()
    monkeypatch.setattr(app, "_client", f)
    monkeypatch.setattr(app.time, "sleep", lambda s: None)
    app._CACHE.clear()
    app._AS_OF.clear()
    return f


def call(fn, **params):
    ev = {"actionGroup": "oil-tools", "function": fn,
          "parameters": [{"name": k, "type": "string", "value": v} for k, v in params.items()]}
    resp = app.lambda_handler(ev, None)
    return resp, json.loads(resp["response"]["functionResponse"]["responseBody"]["TEXT"]["body"])


def test_response_shape_and_sensitivity():
    resp, body = call("get_asset_sensitivity", ticker="tlt")
    assert resp["messageVersion"] == "1.0"
    assert resp["response"]["actionGroup"] == "oil-tools"
    assert resp["response"]["function"] == "get_asset_sensitivity"
    assert body["sensitivity"]["beta_simple"] == -0.123
    assert len(body["rolling"]) == 4
    assert body["as_of"] == "2026-11-13"
    assert "units" in body


@pytest.mark.parametrize("raw,want", [("enb", "ENB.TO"), (" ENB.TO ", "ENB.TO"), ("xom", "XOM"),
                                      ("xiu", "XIU.TO")])
def test_ticker_normalization(raw, want):
    assert app.norm_ticker(raw) == want


@pytest.mark.parametrize("raw,want", [("30", 30), ("+30", 30), ("30%", 30), ("-15", -15),
                                      (" -30 % ", -30), (15, 15)])
def test_shock_normalization(raw, want):
    assert app.norm_shock(raw) == want


@pytest.mark.parametrize("fn,params", [
    ("get_portfolio_exposure", {"persona": "bob"}),
    ("get_asset_sensitivity", {"ticker": "x'; DROP TABLE links;--"}),
    ("explain_channel", {"ticker": "BTC-USD"}),
    ("get_validation", {"ticker": ""}),
    ("run_scenario", {"persona": "robert", "oil_shock_pct": "20"}),
    ("run_scenario", {"persona": "robert", "oil_shock_pct": "30 OR 1=1"}),
    ("compare_alternative", {"persona": "robert", "holding": "QQQ", "alternative": "XIU.TO"}),
    ("get_asset_sensitivity", {}),
    ("nope", {}),
])
def test_bad_input_rejected_without_query(fake, fn, params):
    _, body = call(fn, **params)
    assert "error" in body and isinstance(body["allowed"], list)
    assert fake.sql == []


def test_no_raw_text_in_sql(fake):
    call("get_asset_sensitivity", ticker="enb")
    call("run_scenario", persona="ROBERT", oil_shock_pct="+30%")
    call("compare_alternative", persona="Mateo", holding="vfv", alternative="xsp")
    assert fake.sql
    for s in fake.sql:
        assert s.lstrip().upper().startswith("SELECT")
        assert "enb" not in s and "ROBERT" not in s and "+30" not in s and "Mateo" not in s
        assert "vfv" not in s and "xsp" not in s and "%" not in s
    assert any("'ENB.TO'" in s for s in fake.sql)
    assert any("shock_pct = 30" in s for s in fake.sql)


def test_cache_skips_athena(fake):
    call("get_validation", ticker="TLT")
    n = len(fake.sql)
    _, body = call("get_validation", ticker="tlt")
    assert len(fake.sql) == n
    assert body["validation"]["range"] == [0.1, 0.2]
    assert body["validation"]["beta_ex2022"] == 0.123


def test_explain_channel_macro_fallback_and_size():
    _, body = call("explain_channel", ticker="zst")
    assert body["evidence"][0]["ticker"] == "macro"
    assert {l["link_id"] for l in body["links"]} == {"oil>ca2y", "ca2y>ZST.TO"}
    assert body["duration_check"]["duration_years"] == 0.4
    assert len(json.dumps(body)) < 20000


def test_scenario_and_portfolio_and_alternative():
    _, b = call("run_scenario", persona="robert", oil_shock_pct="30%")
    assert b["scenario"][0]["impact_pct"] == -5
    assert b["holding_impacts"][0]["impact_pct"] == -6
    _, b = call("get_portfolio_exposure", persona="Robert")
    assert b["portfolio_beta"]["beta"] == 0.2 and b["holdings"][0]["ticker"] == "TLT"
    _, b = call("compare_alternative", persona="robert", holding="tlt", alternative="zst")
    assert b["comparison"]["alternative"] == "ZST.TO"


def test_athena_failure_does_not_raise(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(app, "run_query", boom)
    _, body = call("get_validation", ticker="TLT")
    assert "error" in body
