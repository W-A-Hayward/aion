"""cascade-research: GET /research?ticker=XIU.TO -> the table envelope the Research page reads.

Response shape (frontend/api.js TABLES): one JSON array per processed table, filtered to what the
selected ticker needs, plus a "meta" object with the run's as-of week and any tables that could
not be read. Read-only Athena SELECTs from fixed templates; the only interpolated value is a ticker
from the CORE allow-list. Standard library + boto3 only.
"""
import json
import os
import re
import time
from datetime import datetime, timezone

REGION = os.environ.get("AWS_REGION", "us-east-1")
POLL_SECONDS = 0.25
POLL_TIMEOUT = 25.0
CACHE_SECONDS = int(os.environ.get("CACHE_SECONDS", "300"))

# The data contract's 14 MVP tickers: the only ones the Research page offers.
CORE = (
    "XIU.TO", "ENB.TO", "XOM", "TLT", "XBB.TO", "ZST.TO", "QQQ", "SHOP.TO",
    "SPY", "VFV.TO", "XSP.TO", "XESG.TO", "ATD.TO", "RY.TO",
)
EVIDENCE_COLS = "evidence_id, ticker, doc_type, channel, direction, source_url, section, excerpt, s3_key"
REQUIRED = ("sensitivities",)
NUMERIC_TYPES = {"double", "float", "real", "decimal", "integer", "int", "bigint", "smallint", "tinyint"}
INTEGER_TYPES = {"integer", "int", "bigint", "smallint", "tinyint"}

_client = None
_cache = {}


def _athena():
    global _client
    if _client is None:
        import boto3
        _client = boto3.client("athena", region_name=REGION)
    return _client


def _lit(s):
    """SQL string literal for a value from an allow-list (asserted safe)."""
    assert re.fullmatch(r"[A-Za-z0-9.\-]+", s), "unsafe literal"
    return "'%s'" % s


ALL = "ALL"  # ?ticker=ALL: every core ticker in one response, so the page loads its statistics once


def queries(ticker):
    """Table name -> SQL. Every table in frontend/api.js TABLES appears exactly once.

    `ticker` is one core ticker or ALL (then each per-ticker filter becomes IN (<the 14 core tickers>)).
    """
    if ticker == ALL:
        t = "(" + ", ".join(_lit(c) for c in CORE) + ")"
        eq = " IN " + t
        evidence_limit = "300"
    else:
        t = _lit(ticker)
        eq = " = " + t
        evidence_limit = "50"
    return {
        "sensitivities": "SELECT * FROM sensitivities WHERE universe = 'core'",
        "links": "SELECT * FROM links",
        "chain_reconciliation": "SELECT * FROM chain_reconciliation WHERE ticker" + eq,
        "scenarios": "SELECT * FROM scenarios WHERE subject_type = 'ticker' AND subject" + eq
                     + " ORDER BY subject, shock_pct",
        "evidence": "SELECT " + EVIDENCE_COLS + " FROM evidence WHERE ticker" + eq
                    + " ORDER BY evidence_id LIMIT " + evidence_limit,
        "confidence": "SELECT * FROM confidence WHERE ticker" + eq,
        "edges": "SELECT * FROM edges WHERE to_node" + eq,
        "rolling": "SELECT ticker, CAST(week AS varchar) AS week, beta_52w FROM rolling WHERE ticker" + eq
                   + " ORDER BY ticker, week",
        "duration_check": "SELECT * FROM duration_check WHERE ticker" + eq,
        "persona_holdings": "SELECT * FROM persona_holdings ORDER BY persona, weight DESC",
        "portfolio_exposure": "SELECT * FROM portfolio_exposure ORDER BY persona, weight DESC",
        "portfolio_beta": "SELECT * FROM portfolio_beta ORDER BY persona",
        "alternatives": "SELECT * FROM alternatives",
        "_as_of": "SELECT CAST(max(week) AS varchar) AS as_of FROM rolling",
    }


def _start(sql):
    return _athena().start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": os.environ.get("ATHENA_DB", "cascade")},
        WorkGroup=os.environ.get("ATHENA_WORKGROUP", "cascade"),
        ResultConfiguration={"OutputLocation": os.environ.get(
            "ATHENA_OUTPUT", "s3://cascade-s3-bucket/athena-results/")},
    )["QueryExecutionId"]


def _value(raw, col_type):
    if raw is None:
        return None
    t = (col_type or "").lower().split("(")[0]
    if t in INTEGER_TYPES:
        return int(raw)
    if t in NUMERIC_TYPES:
        v = float(raw)
        return v if v == v and v not in (float("inf"), float("-inf")) else None  # NaN/inf -> null
    if t == "boolean":
        return raw.lower() == "true"
    return raw


def _results(qid):
    client = _athena()
    rows, columns, token, first = [], None, None, True
    while True:
        kwargs = {"QueryExecutionId": qid}
        if token:
            kwargs["NextToken"] = token
        page = client.get_query_results(**kwargs)
        if columns is None:
            columns = [(c["Name"], c.get("Type")) for c in page["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]]
        data = page["ResultSet"]["Rows"]
        if first:
            data, first = data[1:], False  # the first row of the first page is the header
        for r in data:
            cells = [c.get("VarCharValue") for c in r["Data"]]
            rows.append({name: _value(v, typ) for (name, typ), v in zip(columns, cells)})
        token = page.get("NextToken")
        if not token:
            return rows


def run_all(sqls):
    """Start every query at once, then poll. Returns (results by name, failed names)."""
    started, failed = {}, []
    for name, sql in sqls.items():
        try:
            started[name] = _start(sql)
        except Exception as e:
            print(json.dumps({"table": name, "status": "START_FAILED", "error": type(e).__name__}))
            failed.append(name)
    pending, done = dict(started), {}
    deadline = time.monotonic() + POLL_TIMEOUT
    while pending:
        for name, qid in list(pending.items()):
            try:
                state = _athena().get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]["State"]
            except Exception as e:
                state = "FAILED"
            if state == "SUCCEEDED":
                try:
                    done[name] = _results(qid)
                except Exception:
                    failed.append(name)
                del pending[name]
            elif state in ("FAILED", "CANCELLED"):
                print(json.dumps({"table": name, "status": state}))
                failed.append(name)
                del pending[name]
        if pending:
            if time.monotonic() >= deadline:
                failed.extend(pending)
                break
            time.sleep(POLL_SECONDS)
    return done, sorted(failed)


def build_envelope(ticker):
    sqls = queries(ticker)
    done, failed = run_all(sqls)
    envelope = {name: done.get(name, []) for name in sqls if not name.startswith("_")}
    as_of = (done.get("_as_of") or [{}])[0].get("as_of")
    envelope["meta"] = {
        "ticker": ticker,
        "as_of": as_of,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "athena:%s" % os.environ.get("ATHENA_DB", "cascade"),
        "missing": [n for n in failed if not n.startswith("_")],
    }
    return envelope, [n for n in failed if n in REQUIRED]


def _cors():
    origin = os.environ.get("ALLOWED_ORIGIN")
    return {"access-control-allow-origin": origin, "vary": "Origin"} if origin else {}


def _resp(code, body, cache=False):
    headers = {"content-type": "application/json", **_cors(),
               "cache-control": "public, max-age=%d" % CACHE_SECONDS if cache else "no-store"}
    return {"statusCode": code, "headers": headers, "body": json.dumps(body, allow_nan=False)}


def lambda_handler(event, context):
    event = event if isinstance(event, dict) else {}
    method = ((event.get("requestContext") or {}).get("http") or {}).get("method")
    if method == "OPTIONS":
        return _resp(204, {})
    raw = ((event.get("queryStringParameters") or {}).get("ticker") or "").strip().upper()
    ticker = ALL if raw == ALL else raw if raw in CORE else raw + ".TO" if raw + ".TO" in CORE else None
    if ticker is None:
        return _resp(400, {"error": "unknown ticker", "allowed": list(CORE) + [ALL]})
    hit = _cache.get(ticker)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return _resp(200, hit[1], cache=True)
    started = time.time()
    envelope, required_failed = build_envelope(ticker)
    print(json.dumps({"ticker": ticker, "missing": envelope["meta"]["missing"],
                      "durationMs": int((time.time() - started) * 1000)}))
    if required_failed:
        return _resp(502, {"error": "the sensitivities table could not be read", "missing": required_failed})
    if ticker != ALL and not any(row.get("ticker") == ticker for row in envelope["sensitivities"]):
        return _resp(404, {"error": "no sensitivity row for %s in this run" % ticker})
    if not envelope["meta"]["missing"]:
        _cache[ticker] = (time.time(), envelope)
    return _resp(200, envelope, cache=not envelope["meta"]["missing"])
