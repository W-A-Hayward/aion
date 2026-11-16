import importlib.util
import json
import os
import re

import pytest

_spec = importlib.util.spec_from_file_location("research_app", os.path.join(os.path.dirname(__file__), "app.py"))
app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(app)

FRONTEND_TABLES = ["sensitivities", "links", "chain_reconciliation", "scenarios", "evidence", "confidence",
                   "edges", "rolling", "duration_check", "persona_holdings", "portfolio_beta", "alternatives"]

SENS = [{"ticker": "XIU.TO", "beta_simple": "0.010571", "n_weeks": "261", "universe": "core", "market_ticker": None},
        {"ticker": "TLT", "beta_simple": "-0.089257", "n_weeks": "261", "universe": "core", "market_ticker": "SPY"}]
TYPES = {"ticker": "varchar", "beta_simple": "double", "n_weeks": "bigint", "universe": "varchar",
         "market_ticker": "varchar", "week": "varchar", "beta_52w": "double", "as_of": "varchar",
         "shock_pct": "bigint", "impact_pct": "double"}


class FakeAthena:
    """Answers by matching the FROM table; can fail chosen tables or never finish them."""

    def __init__(self, fail=(), hang=(), nan_beta=False):
        self.fail, self.hang, self.nan_beta = set(fail), set(hang), nan_beta
        self.sql, self.started = {}, []

    def _table(self, sql):
        if "max(week)" in sql:
            return "_as_of"
        return re.search(r"FROM (\w+)", sql).group(1)

    def start_query_execution(self, QueryString, **kw):
        qid = "q%d" % len(self.started)
        self.started.append(QueryString)
        self.sql[qid] = QueryString
        return {"QueryExecutionId": qid}

    def get_query_execution(self, QueryExecutionId):
        t = self._table(self.sql[QueryExecutionId])
        state = "FAILED" if t in self.fail else "RUNNING" if t in self.hang else "SUCCEEDED"
        return {"QueryExecution": {"Status": {"State": state}}}

    def get_query_results(self, QueryExecutionId, **kw):
        t = self._table(self.sql[QueryExecutionId])
        rows = {"sensitivities": SENS, "_as_of": [{"as_of": "2026-11-13"}],
                "rolling": [{"ticker": "XIU.TO", "week": "2026-11-06", "beta_52w": "NaN" if self.nan_beta else "0.02"}],
                "scenarios": [{"shock_pct": "30", "impact_pct": "0.2777"}]}.get(t, [])
        cols = list(rows[0]) if rows else ["ticker"]
        header = {"Data": [{"VarCharValue": c} for c in cols]}
        data = [{"Data": [{} if r.get(c) is None else {"VarCharValue": r[c]} for c in cols]} for r in rows]
        return {"ResultSet": {"ResultSetMetadata": {"ColumnInfo": [{"Name": c, "Type": TYPES.get(c, "varchar")} for c in cols]},
                              "Rows": [header] + data}}


@pytest.fixture
def athena(monkeypatch):
    def make(**kw):
        fake = FakeAthena(**kw)
        monkeypatch.setattr(app, "_athena", lambda: fake)
        app._cache.clear()
        return fake
    monkeypatch.setattr(app.time, "sleep", lambda s: None)
    return make


def get(ticker):
    return app.lambda_handler({"queryStringParameters": {"ticker": ticker}, "requestContext": {"http": {"method": "GET"}}}, None)


def test_envelope_matches_frontend_contract(athena):
    athena()
    r = get("XIU.TO")
    assert r["statusCode"] == 200
    body = json.loads(r["body"])
    for name in FRONTEND_TABLES:
        assert isinstance(body[name], list), name
    assert body["meta"]["ticker"] == "XIU.TO" and body["meta"]["as_of"] == "2026-11-13"
    assert body["meta"]["missing"] == []
    xiu = body["sensitivities"][0]
    assert xiu == {"ticker": "XIU.TO", "beta_simple": 0.010571, "n_weeks": 261, "universe": "core", "market_ticker": None}
    assert body["scenarios"][0]["shock_pct"] == 30 and isinstance(body["scenarios"][0]["impact_pct"], float)
    assert r["headers"]["cache-control"].startswith("public")


def test_short_ticker_and_case_accepted(athena):
    athena()
    assert json.loads(get("xiu")["body"])["meta"]["ticker"] == "XIU.TO"


@pytest.mark.parametrize("bad", ["", "AAPL", "XEG.TO", "XIU.TO' OR 1=1 --", "x" * 50])
def test_rejects_unsupported_ticker(athena, bad):
    fake = athena()
    r = get(bad)
    assert r["statusCode"] == 400 and "XIU.TO" in json.loads(r["body"])["allowed"]
    assert fake.started == []


def test_only_allow_listed_literal_reaches_sql(athena):
    fake = athena()
    get("ENB.TO")
    literals = set(re.findall(r"'([^']*)'", " ".join(fake.started)))
    assert literals <= {"core", "ticker", "ENB.TO"}


def test_queries_run_concurrently(athena):
    fake = athena()
    get("TLT")
    assert len(fake.started) == len(app.queries("TLT"))  # all started before any result was read


def test_optional_table_failure_is_reported_not_hidden(athena, monkeypatch):
    monkeypatch.setattr(app, "POLL_TIMEOUT", 0.05)
    athena(fail={"evidence"}, hang={"rolling"})
    r = get("XIU.TO")
    body = json.loads(r["body"])
    assert r["statusCode"] == 200
    assert body["evidence"] == [] and body["rolling"] == []
    assert body["meta"]["missing"] == ["evidence", "rolling"]
    assert r["headers"]["cache-control"] == "no-store"


def test_required_table_failure_is_an_error(athena):
    athena(fail={"sensitivities"})
    r = get("XIU.TO")
    assert r["statusCode"] == 502


def test_ticker_missing_from_run(athena, monkeypatch):
    athena()
    r = get("RY.TO")
    assert r["statusCode"] == 404


def test_nan_becomes_null_and_body_is_strict_json(athena):
    athena(nan_beta=True)
    body = json.loads(get("XIU.TO")["body"])
    assert body["rolling"][0]["beta_52w"] is None


def test_cache_serves_repeat_requests(athena):
    fake = athena()
    get("XIU.TO")
    n = len(fake.started)
    get("XIU.TO")
    assert len(fake.started) == n


def test_preflight_and_cors(athena, monkeypatch):
    athena()
    monkeypatch.setenv("ALLOWED_ORIGIN", "https://cascade.example")
    assert app.lambda_handler({"requestContext": {"http": {"method": "OPTIONS"}}}, None)["statusCode"] == 204
    assert get("XIU.TO")["headers"]["access-control-allow-origin"] == "https://cascade.example"


def test_covers_every_table_the_frontend_reads():
    """frontend/api.js TABLES is the page's contract; the endpoint must return each one."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "api.js")).read()
    block = re.search(r"TABLES = Object\.freeze\(\[(.*?)\]\)", src, re.S).group(1)
    frontend = set(re.findall(r"'([a-z_]+)'", block))
    assert frontend and frontend <= {n for n in app.queries("XIU.TO") if not n.startswith("_")}


def test_all_tickers_in_one_response(athena):
    fake = athena()
    r = get("all")
    assert r["statusCode"] == 200
    body = json.loads(r["body"])
    assert body["meta"]["ticker"] == "ALL"
    sql = [q for q in fake.started if "FROM rolling WHERE" in q or "FROM scenarios WHERE" in q]
    assert sql and all("IN ('XIU.TO', 'ENB.TO'" in q for q in sql), "per-ticker filters cover every core ticker"
    n = len(fake.started)
    get("ALL")
    assert len(fake.started) == n, "ALL is cached like a single ticker"
