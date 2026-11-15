"""cascade-tools: one Lambda serving six Bedrock Agent functions (function-details action group).

Read-only Athena SELECTs from fixed templates. Every value interpolated into SQL is a constant
taken from the allow-lists below, never the raw user text.
"""
import json
import os
import re
import time

REGION = "us-east-1"
MAX_BODY_BYTES = 20000
POLL_SECONDS = 0.3
POLL_TIMEOUT = 20.0

PERSONAS = ("robert", "amira", "mateo")
SHOCKS = (-30, -15, 15, 30)
CORE = (
    "XIU.TO", "ENB.TO", "XOM", "TLT", "XBB.TO", "ZST.TO", "QQQ", "SHOP.TO",
    "SPY", "VFV.TO", "XSP.TO", "XESG.TO", "ATD.TO", "RY.TO",
)
EXTRA = (
    "CNQ.TO", "CNR.TO", "FTS.TO", "TD.TO", "MFC.TO", "CSU.TO", "NVDA", "AAPL", "MSFT",
    "GOOGL", "AMZN", "TSLA", "JPM", "JNJ", "PG", "GLD", "AGG", "ESGV", "XRB.TO", "XLB.TO", "XEG.TO",
)
UNIVERSE = CORE + EXTRA
PAIRS = (
    ("robert", "TLT", "ZST.TO"),
    ("robert", "XBB.TO", "ZST.TO"),
    ("mateo", "XIU.TO", "XESG.TO"),
    ("mateo", "VFV.TO", "XSP.TO"),
    ("amira", "QQQ", "XIU.TO"),
)
CHANNELS = ("direct", "rates", "currency", "company-specific", "none")
FUNCTIONS = (
    "get_portfolio_exposure", "get_asset_sensitivity", "explain_channel",
    "run_scenario", "compare_alternative", "get_validation",
)

BETA_UNITS = (
    "beta: % move of the asset for a 1% move in Brent, weekly, 2021-11 to latest, in CAD; "
    "lo/hi: 95% range (HAC 4 lags); p: p-value"
)

_CACHE = {}
_AS_OF = {}
_client = None


class InputError(Exception):
    def __init__(self, message, allowed):
        super().__init__(message)
        self.message = message
        self.allowed = list(allowed)


# ----------------------------------------------------------------------------- input validation

def norm_persona(value):
    v = str(value if value is not None else "").strip().lower()
    if v in PERSONAS:
        return v
    raise InputError("unknown persona", PERSONAS)


def norm_ticker(value):
    v = str(value if value is not None else "").strip().upper()
    if v in UNIVERSE:
        return v
    if v + ".TO" in UNIVERSE:
        return v + ".TO"
    raise InputError("unknown ticker", UNIVERSE)


def norm_shock(value):
    v = str(value if value is not None else "").strip().replace("%", "").replace(" ", "")
    if re.fullmatch(r"[+-]?\d{1,3}(\.0+)?", v):
        n = int(float(v))
        if n in SHOCKS:
            return n
    raise InputError("oil_shock_pct must be one of the allowed values", ["%+d" % s for s in SHOCKS])


def norm_pair(persona, holding, alternative):
    p = norm_persona(persona)
    h = norm_ticker(holding)
    a = norm_ticker(alternative)
    if (p, h, a) in PAIRS:
        return p, h, a
    raise InputError("no such alternative for this persona",
                     ["%s: %s -> %s" % t for t in PAIRS])


# ----------------------------------------------------------------------------- Athena

def _athena():
    global _client
    if _client is None:
        import boto3
        _client = boto3.client("athena", region_name=REGION)
    return _client


def _convert(value):
    if value is None:
        return None
    if re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", value):
        return float(value)
    return value


def run_query(sql):
    """Run one read-only SELECT; return list of dicts. Raises RuntimeError on failure."""
    client = _athena()
    qid = client.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": os.environ.get("ATHENA_DB", "cascade")},
        WorkGroup=os.environ.get("ATHENA_WORKGROUP", "cascade"),
        ResultConfiguration={
            "OutputLocation": os.environ.get("ATHENA_OUTPUT", "s3://cascade-s3-bucket/athena-results/")
        },
    )["QueryExecutionId"]
    deadline = time.monotonic() + POLL_TIMEOUT
    while True:
        status = client.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        state = status["State"]
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            raise RuntimeError("athena query %s" % state.lower())
        if time.monotonic() >= deadline:
            raise RuntimeError("athena query timed out")
        time.sleep(POLL_SECONDS)

    rows, header, token = [], None, None
    while True:
        kwargs = {"QueryExecutionId": qid}
        if token:
            kwargs["NextToken"] = token
        page = client.get_query_results(**kwargs)
        for r in page["ResultSet"]["Rows"]:
            cells = [c.get("VarCharValue") for c in r["Data"]]
            if header is None:
                header = cells
            else:
                rows.append({h: _convert(c) for h, c in zip(header, cells)})
        token = page.get("NextToken")
        if not token:
            return rows


def _lit(s):
    """SQL string literal for a constant from an allow-list (asserted safe)."""
    assert re.fullmatch(r"[A-Za-z0-9.\-]+", s), "unsafe literal"
    return "'%s'" % s


def get_as_of():
    if "v" not in _AS_OF:
        rows = run_query("SELECT CAST(max(week) AS varchar) AS as_of FROM rolling")
        _AS_OF["v"] = rows[0]["as_of"] if rows else None
    return _AS_OF["v"]


# ----------------------------------------------------------------------------- tools

def _first(rows):
    return rows[0] if rows else None


def get_portfolio_exposure(persona):
    p = _lit(persona)
    holdings = run_query(
        "SELECT h.ticker AS ticker, h.weight AS weight, e.beta AS beta, e.lo AS lo, e.hi AS hi, "
        "e.contribution AS contribution "
        "FROM persona_holdings h JOIN portfolio_exposure e "
        "ON h.persona = e.persona AND h.ticker = e.ticker "
        "WHERE h.persona = " + p + " ORDER BY h.weight DESC, h.ticker LIMIT 20"
    )
    pb = _first(run_query(
        "SELECT beta, lo, hi, p, r2, n_weeks FROM portfolio_beta WHERE persona = " + p + " LIMIT 1"
    ))
    return {
        "persona": persona,
        "holdings": holdings,
        "portfolio_beta": pb,
        "units": BETA_UNITS + "; weight: share of portfolio; contribution: weight x beta "
                 "(portfolio beta measured on the portfolio itself)",
    }


def get_asset_sensitivity(ticker):
    t = _lit(ticker)
    row = _first(run_query("SELECT * FROM sensitivities WHERE ticker = " + t + " LIMIT 1"))
    rolling = run_query(
        "SELECT CAST(week AS varchar) AS week, beta_52w FROM rolling WHERE ticker = " + t +
        " ORDER BY week DESC LIMIT 4"
    )
    rolling.reverse()
    out = {
        "ticker": ticker,
        "sensitivity": row,
        "rolling": rolling,
        "units": BETA_UNITS + "; beta_simple: vs Brent only; beta_mkt: controlling for the market; "
                 "rolling beta_52w: 52-week window ending that week",
    }
    if rolling:
        out["as_of"] = rolling[-1]["week"]
    return out


def explain_channel(ticker):
    t = _lit(ticker)
    conf = _first(run_query("SELECT * FROM confidence WHERE ticker = " + t + " LIMIT 1"))
    chains = run_query("SELECT * FROM chain_reconciliation WHERE ticker = " + t + " LIMIT 5")
    all_links = run_query("SELECT * FROM links LIMIT 50")
    wanted = set()
    for c in chains:
        nodes = str(c.get("chain") or "").split(">")
        for a, b in zip(nodes, nodes[1:]):
            wanted.add("%s>%s" % (a, b))
    links = [l for l in all_links if l.get("link_id") in wanted]
    duration = _first(run_query("SELECT * FROM duration_check WHERE ticker = " + t + " LIMIT 1"))
    cols = "evidence_id, ticker, doc_type, channel, direction, source_url, section, excerpt"
    evidence = run_query(
        "SELECT " + cols + " FROM evidence WHERE ticker = " + t + " ORDER BY evidence_id LIMIT 3"
    )
    if not evidence and conf and conf.get("channel") in CHANNELS:
        evidence = run_query(
            "SELECT " + cols + " FROM evidence WHERE ticker = 'macro' AND channel = " +
            _lit(conf["channel"]) + " ORDER BY evidence_id LIMIT 2"
        )
    return {
        "ticker": ticker,
        "confidence": conf,
        "chains": chains,
        "links": links,
        "duration_check": duration,
        "evidence": evidence,
        "units": "beta_direct/beta_chain: % move per 1% move in Brent (weekly, CAD); share_explained: "
                 "beta_chain / beta_direct; link beta: % move (yield links in percentage points) per 1% "
                 "move in the previous node; duration_years: effective duration; moves in % or bp as named",
    }


def run_scenario(persona, shock):
    p = _lit(persona)
    scen = run_query(
        "SELECT subject, subject_type, shock_pct, impact_pct, lo_pct, hi_pct FROM scenarios "
        "WHERE subject_type = 'persona' AND subject = " + p + " AND shock_pct = " + str(int(shock)) +
        " LIMIT 5"
    )
    exposure = run_query(
        "SELECT ticker, weight, beta, lo, hi, contribution FROM portfolio_exposure "
        "WHERE persona = " + p + " ORDER BY weight DESC, ticker LIMIT 20"
    )
    impacts = []
    for e in exposure:
        try:
            impacts.append({
                "ticker": e["ticker"],
                "weight": e["weight"],
                "impact_pct": e["beta"] * shock,
                "lo_pct": min(e["lo"] * shock, e["hi"] * shock),
                "hi_pct": max(e["lo"] * shock, e["hi"] * shock),
                "contribution_pct": e["contribution"] * shock,
            })
        except (TypeError, KeyError):
            continue
    return {
        "persona": persona,
        "oil_shock_pct": shock,
        "scenario": scen,
        "holding_impacts": impacts,
        "units": "impact_pct: estimated % change in value for a Brent move of oil_shock_pct %, = beta x shock "
                 "(linear, weekly beta, CAD); lo_pct/hi_pct: 95% range; contribution_pct: weight x impact",
    }


def compare_alternative(persona, holding, alternative):
    row = _first(run_query(
        "SELECT persona, holding, alternative, beta_holding, beta_alternative, impact30_before_pct, "
        "impact30_after_pct FROM alternatives WHERE persona = " + _lit(persona) +
        " AND holding = " + _lit(holding) + " AND alternative = " + _lit(alternative) + " LIMIT 1"
    ))
    return {
        "persona": persona,
        "holding": holding,
        "alternative": alternative,
        "comparison": row,
        "units": "beta_*: % move per 1% move in Brent (weekly, CAD); impact30_*_pct: portfolio impact in % "
                 "of a +30% Brent move before and after the swap",
    }


def get_validation(ticker):
    row = _first(run_query(
        "SELECT s.beta_ex2022 AS beta_ex2022, s.lo_ex2022 AS lo_ex2022, s.hi_ex2022 AS hi_ex2022, "
        "s.oos_hit_rate AS oos_hit_rate, s.oos_n AS oos_n, s.beta_up AS beta_up, "
        "s.beta_down AS beta_down, c.label AS label, c.reason_text AS reason_text "
        "FROM sensitivities s LEFT JOIN confidence c ON s.ticker = c.ticker "
        "WHERE s.ticker = " + _lit(ticker) + " LIMIT 1"
    ))
    out = {"ticker": ticker, "validation": None,
           "units": "beta_ex2022: beta excluding 2022, range = 95% (lo_ex2022, hi_ex2022); oos_hit_rate: share "
                    "of out-of-sample weeks (2025+) where the sign of the move was predicted, over oos_n weeks; "
                    "beta_up/beta_down: beta in weeks with oil up/down; label: green|yellow|grey"}
    if row:
        out["validation"] = {
            "beta_ex2022": row.get("beta_ex2022"),
            "range": [row.get("lo_ex2022"), row.get("hi_ex2022")],
            "oos_hit_rate": row.get("oos_hit_rate"),
            "oos_n": row.get("oos_n"),
            "beta_up": row.get("beta_up"),
            "beta_down": row.get("beta_down"),
            "label": row.get("label"),
            "reason_text": row.get("reason_text"),
        }
    return out


# ----------------------------------------------------------------------------- plumbing

def _params(event):
    params = event.get("parameters") or []
    out = {}
    if isinstance(params, list):
        for p in params:
            if isinstance(p, dict) and "name" in p:
                out[str(p["name"])] = p.get("value")
    return out


def _require(params, names):
    for n in names:
        if n not in params:
            raise InputError("missing parameter: " + n, names)


def _round(x):
    if isinstance(x, float):
        return round(x, 3)
    if isinstance(x, dict):
        return {k: _round(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_round(v) for v in x]
    return x


def _fit(result):
    """Shrink the result until its JSON is under MAX_BODY_BYTES."""
    def size():
        return len(json.dumps(result).encode("utf-8"))
    limit = 800
    while size() > MAX_BODY_BYTES and limit >= 50:
        for row in result.get("evidence") or []:
            if isinstance(row.get("excerpt"), str):
                row["excerpt"] = row["excerpt"][:limit]
        limit //= 2
    while size() > MAX_BODY_BYTES and result.get("evidence"):
        result["evidence"].pop()
    return result


def _dispatch(fn, params):
    """Validate, then return (cache_key, thunk)."""
    if fn == "get_portfolio_exposure":
        _require(params, ["persona"])
        p = norm_persona(params["persona"])
        return (fn, p), lambda: get_portfolio_exposure(p)
    if fn in ("get_asset_sensitivity", "explain_channel", "get_validation"):
        _require(params, ["ticker"])
        t = norm_ticker(params["ticker"])
        return (fn, t), lambda: globals()[fn](t)
    if fn == "run_scenario":
        _require(params, ["persona", "oil_shock_pct"])
        p = norm_persona(params["persona"])
        s = norm_shock(params["oil_shock_pct"])
        return (fn, p, s), lambda: run_scenario(p, s)
    if fn == "compare_alternative":
        _require(params, ["persona", "holding", "alternative"])
        p, h, a = norm_pair(params["persona"], params["holding"], params["alternative"])
        return (fn, p, h, a), lambda: compare_alternative(p, h, a)
    raise InputError("unknown function", FUNCTIONS)


def run(event):
    fn = event.get("function")
    try:
        key, thunk = _dispatch(fn, _params(event))
    except InputError as e:
        return {"error": e.message, "allowed": e.allowed}
    if key in _CACHE:
        return _CACHE[key]
    try:
        result = thunk()
        if "as_of" not in result:
            result["as_of"] = get_as_of()
        result = _fit(_round(result))
    except Exception as e:  # never raise to the agent
        return {"error": "query failed: %s" % type(e).__name__, "allowed": []}
    _CACHE[key] = result
    return result


def lambda_handler(event, context):
    result = run(event if isinstance(event, dict) else {})
    event = event if isinstance(event, dict) else {}
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get("actionGroup"),
            "function": event.get("function"),
            "functionResponse": {
                "responseBody": {"TEXT": {"body": json.dumps(result)}}
            },
        },
    }
