"""cascade-tools: one Lambda serving eight Bedrock Agent functions (function-details action group).

Read-only Athena SELECTs from fixed templates. Every value interpolated into SQL is a constant
taken from the allow-lists below, never the raw user text.
"""
import json
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

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
    "get_portfolio_facts", "test_shield",
)

SHOCK_TYPES = ("oil", "rates")
MAX_RATES_BP = 300
# Shield names that are not universe tickers (see shields / shield_by_crash_type in the data contract).
EXTRA_SHIELDS = ("usdcad", "TLT_usd")
SHIELD_ORDER = ("usdcad", "GLD", "ZST.TO", "XBB.TO", "AGG", "TLT_usd")
BOND_TICKERS = ("TLT", "XBB.TO", "ZST.TO")
# Measured yield links: ticker -> (yield node, link_id). Beta unit: log return per 1 pp yield change.
RATES_LINKS = {
    "TLT": ("us10y", "us10y>TLT"),
    "XBB.TO": ("ca10y", "ca10y>XBB.TO"),
    "XLB.TO": ("ca10y", "ca10y>XLB.TO"),
    "XRB.TO": ("ca10y", "ca10y>XRB.TO"),
    "ZST.TO": ("ca2y", "ca2y>ZST.TO"),
}
FACTS_WINDOW = "2021-2026"
FACTS_NOTE = "2021-2026 only; past behaviour; descriptive"
BASE_THRESHOLD_SET = "-2/+10"
CUSHION_CANDIDATES = ("usdcad", "GLD", "ZST.TO", "XBB.TO", "AGG", "TLT_usd")
STOCK_BOND_PAIRS = ("XIU.TO/XBB.TO", "SPY/TLT")
EVIDENCE_TOPICS = ("currency", "stock_bond")
EVIDENCE_PER_TOPIC = 4
EXCERPT_CHARS = 400
WORST_WEEKS_DIVISOR = 10     # worst weeks = bottom 10% of weeks, count rounded up
SIGNIFICANCE_P = 0.05
FACTS_DIGITS = 2

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


def norm_shock_type(value):
    v = str(value if value is not None else "").strip().lower()
    if v == "":
        return "oil"
    if v in SHOCK_TYPES:
        return v
    raise InputError("shock_type must be one of the allowed values", SHOCK_TYPES)


def norm_rates_bp(value):
    v = str(value if value is not None else "").strip().lower().replace("bp", "").replace(" ", "")
    if re.fullmatch(r"[+-]?\d{1,3}(\.0+)?", v):
        n = int(float(v))
        if n != 0 and abs(n) <= MAX_RATES_BP:
            return n
    raise InputError("rates_shock_bp must be a non-zero whole number of basis points, at most %d in size"
                     % MAX_RATES_BP, ["-%d to +%d (not 0)" % (MAX_RATES_BP, MAX_RATES_BP)])


def norm_shield(value):
    """A universe ticker or one of the extra shield names (usdcad, TLT_usd)."""
    raw = str(value if value is not None else "").strip()
    for name in EXTRA_SHIELDS:
        if raw.lower() == name.lower():
            return name
    v = raw.upper()
    if v in UNIVERSE:
        return v
    if v + ".TO" in UNIVERSE:
        return v + ".TO"
    raise InputError("not in universe", UNIVERSE + EXTRA_SHIELDS)


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
    assert re.fullmatch(r"[A-Za-z0-9._>\-]+", s), "unsafe literal"
    return "'%s'" % s


def _in_list(values):
    return "(" + ", ".join(_lit(v) for v in values) + ")"


def _run_all(queries):
    """Run several independent SELECTs in parallel; return {name: rows}."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {name: pool.submit(run_query, sql) for name, sql in queries.items()}
        return {name: f.result() for name, f in futures.items()}


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
    log_shock = math.log(1 + shock / 100.0)

    def impact(beta):
        return 100 * (math.exp(beta * log_shock) - 1)

    impacts = []
    for e in exposure:
        try:
            lo, hi = sorted((impact(e["lo"]), impact(e["hi"])))
            point = impact(e["beta"])
            impacts.append({
                "ticker": e["ticker"],
                "weight": e["weight"],
                "impact_pct": point,
                "lo_pct": lo,
                "hi_pct": hi,
                "contribution_pct": e["weight"] * point,
            })
        except (TypeError, KeyError):
            continue
    return {
        "persona": persona,
        "shock_type": "oil",
        "oil_shock_pct": shock,
        "scenario": scen,
        "holding_impacts": impacts,
        "note": "holding contributions need not sum exactly to the portfolio impact, "
                "which is measured on the portfolio itself",
        "units": "impact_pct: estimated % change in value for a Brent move of oil_shock_pct %, "
                 "= 100 x (exp(beta x ln(1 + shock/100)) - 1) (log formula, weekly beta, CAD); "
                 "lo_pct/hi_pct: 95% range from the beta range, ordered low to high; "
                 "contribution_pct: weight x impact_pct",
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


# ----------------------------------------------------------------------------- rates scenario

def run_scenario_rates(persona, bp):
    """Rates shock: us10y, ca10y (and ca2y for ZST.TO) move by `bp` basis points, through measured links."""
    ids = [link_id for _, link_id in RATES_LINKS.values()]
    got = _run_all({
        "holdings": "SELECT ticker, weight FROM persona_holdings WHERE persona = " + _lit(persona) +
                    " ORDER BY weight DESC, ticker LIMIT 20",
        "links": "SELECT link_id, from_node, to_node, beta, lo, hi, p, unit FROM links WHERE link_id IN " +
                 _in_list(ids) + " LIMIT 20",
    })
    links = {l["link_id"]: l for l in got["links"] if _num(l.get("beta")) is not None}
    pp = bp / 100.0

    def impact(beta):
        return 100 * (math.exp(beta * pp) - 1)

    holdings, not_linked, used = [], [], {}
    total = {"weight_linked": 0.0, "impact_pct": 0.0, "lo_pct": 0.0, "hi_pct": 0.0,
             "per_100k": 0.0, "lo_per_100k": 0.0, "hi_per_100k": 0.0}
    for h in got["holdings"]:
        t, w = h["ticker"], h["weight"]
        link = links.get(RATES_LINKS.get(t, (None, None))[1])
        if link is None or _num(link.get("lo")) is None or _num(link.get("hi")) is None:
            not_linked.append({"ticker": t, "weight": w})
            continue
        point = impact(link["beta"])
        lo, hi = sorted((impact(link["lo"]), impact(link["hi"])))
        holdings.append({
            "ticker": t, "weight": w, "link": link["link_id"],
            "impact_pct": point, "lo_pct": lo, "hi_pct": hi,
            "per_100k": w * point * 1000, "lo_per_100k": w * lo * 1000, "hi_per_100k": w * hi * 1000,
        })
        used[link["link_id"]] = {k: link.get(k) for k in ("link_id", "from_node", "to_node", "beta", "lo", "hi", "p", "unit")}
        total["weight_linked"] += w
        total["impact_pct"] += w * point
        total["lo_pct"] += w * lo
        total["hi_pct"] += w * hi
        total["per_100k"] += w * point * 1000
        total["lo_per_100k"] += w * lo * 1000
        total["hi_per_100k"] += w * hi * 1000
    return {
        "persona": persona,
        "shock_type": "rates",
        "rates_shock_bp": bp,
        "holdings": holdings,
        "not_linked": not_linked,
        "total": total,
        "links_used": list(used.values()),
        "note": "total covers only the linked holdings (weight_linked of the portfolio); holdings in not_linked "
                "have no measured rates link and are not included. us10y and ca10y (and ca2y for ZST.TO) are "
                "all shifted by the same bp (parallel shift). Total ranges add the holding ranges, so they are "
                "wide. Weekly betas applied to a move that may be larger than any single week: indicative only.",
        "units": "impact_pct: estimated % change in the holding for a yield move of rates_shock_bp bp = "
                 "100 x (exp(beta x bp/100) - 1) (link beta: log return per 1 pp yield change, weekly, CAD); "
                 "lo_pct/hi_pct: 95% range from the link range, ordered low to high; per_100k: dollars on "
                 "$100,000 of the whole portfolio = weight x impact_pct x 1000; total.impact_pct and "
                 "total.per_100k are portfolio-level sums over linked holdings",
    }


# ----------------------------------------------------------------------------- shields

def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) and not math.isnan(x) else None


def _txt(x):
    """Text from a cell that _convert may have turned into a float (for example a bare year)."""
    if x is None:
        return None
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x)


def binom_two_sided(k, n):
    """Exact two-sided binomial p-value of k successes in n trials against p = 0.5."""
    if n <= 0:
        return None
    tail = sum(math.comb(n, i) for i in range(0, min(k, n - k) + 1)) / 2.0 ** n
    return min(1.0, 2 * tail)


def shield_label(avg_pct, weeks_up, weeks, binom_p):
    """Shield rules from the data contract (HIDDEN and REMOVED only apply to usdcad and twin rows)."""
    if not weeks:
        return None
    if avg_pct <= 0:
        return "BROKEN"
    if weeks_up / weeks >= 0.6 and binom_p is not None and binom_p < 0.10:
        return "WORKING"
    return "NEUTRAL"


def _worst_weeks(persona_rows):
    """Weeks of the persona's bottom 10% simple returns (count rounded up, ties by earlier week)."""
    series = sorted(((math.expm1(r["ret_cad"]), r["week"]) for r in persona_rows
                     if _num(r.get("ret_cad")) is not None))
    k = -(-len(series) // WORST_WEEKS_DIVISOR)
    return [w for _, w in series[:k]]


def test_shield(persona, ticker):
    p, t = _lit(persona), _lit(ticker)
    got = _run_all({
        "shield": "SELECT item, label, avg_pct_worst, weeks_up, weeks, binom_p FROM shields WHERE persona = " +
                  p + " AND item = " + t + " LIMIT 1",
        "crash": "SELECT threshold_set, crash_type, n_weeks, avg_pct, weeks_up, binom_p FROM shield_by_crash_type "
                 "WHERE shield = " + t + " ORDER BY threshold_set, crash_type LIMIT 20",
        "held": "SELECT ticker FROM persona_holdings WHERE persona = " + p + " LIMIT 20",
    })
    held = ticker in {r["ticker"] for r in got["held"]}
    row = _first(got["shield"])
    source = "shields"
    if row:
        row = {k: row.get(k) for k in ("label", "avg_pct_worst", "weeks_up", "weeks", "binom_p")}
    else:
        source = "weekly_returns"
        if ticker in EXTRA_SHIELDS:
            row = None  # usdcad / TLT_usd come only from the shields table (skipped for holders)
        else:
            rows = _run_all({
                "persona": "SELECT CAST(week AS varchar) AS week, ret_cad FROM weekly_returns "
                           "WHERE subject_or_ticker = " + p + " ORDER BY week LIMIT 1000",
                "ticker": "SELECT CAST(week AS varchar) AS week, ret_cad FROM weekly_returns "
                          "WHERE subject_or_ticker = " + t + " ORDER BY week LIMIT 1000",
            })
            by_week = {r["week"]: math.expm1(r["ret_cad"]) for r in rows["ticker"]
                       if _num(r.get("ret_cad")) is not None}
            vals = [by_week[w] for w in _worst_weeks(rows["persona"]) if w in by_week]
            if vals:
                avg = 100 * sum(vals) / len(vals)
                up = sum(1 for v in vals if v > 0)
                bp = binom_two_sided(up, len(vals))
                row = {"label": shield_label(avg, up, len(vals), bp), "avg_pct_worst": avg,
                       "weeks_up": up, "weeks": len(vals), "binom_p": bp}
    out = {
        "persona": persona,
        "ticker": ticker,
        "held_by_persona": held,
        "worst_weeks": row,
        "source": source,
        "by_crash_type": got["crash"],
        "units": "worst_weeks: the ticker's weekly CAD simple return in the persona's worst 10% portfolio weeks "
                 "(count rounded up, ties by earlier date): avg_pct_worst = mean in %, weeks_up = weeks with "
                 "return > 0, weeks = weeks with data, binom_p = exact two-sided binomial p of weeks_up vs 0.5; "
                 "label: WORKING (avg > 0, weeks_up/weeks >= 0.6, binom_p < 0.10), BROKEN (avg <= 0), HIDDEN "
                 "(usdcad row that meets the WORKING rules while the persona holds USD assets), REMOVED (hedged "
                 "twin with the deeper max drawdown), else NEUTRAL; by_crash_type: market-level weekly "
                 "returns by crash type (stock_crash: XIU.TO below the stock cut-off; rate_shock: US 10y above "
                 "the rate cut-off with no stock crash; other) at three threshold_set levels "
                 "(stock % / rate bp). " + FACTS_NOTE,
    }
    if held:
        out["note"] = "the persona holds this ticker: its own holding is part of the worst weeks, so it " \
                      "tends to be BROKEN by construction"
    if row is None:
        out["worst_weeks_note"] = "no row for this persona (it holds it or there are no returns)"
    return out


# ----------------------------------------------------------------------------- portfolio facts

def _month(week):
    return str(week)[:7]


def _drawdown_by_month(rows):
    """{month: deepest drawdown % within the month}; wealth starts at 1.0, weekly returns compounded."""
    wealth = peak = 1.0
    out = {}
    for r in sorted((r for r in rows if _num(r.get("ret_cad")) is not None), key=lambda r: r["week"]):
        wealth *= math.exp(r["ret_cad"])   # exp(log(1 + simple)) = 1 + simple
        peak = max(peak, wealth)
        dd = (wealth / peak - 1.0) * 100
        m = _month(r["week"])
        out[m] = min(out.get(m, 0.0), dd)
    return out


def _shield_matrix(rows):
    by = {}
    for r in rows:
        by.setdefault((r["shield"], r["crash_type"]), {})[r["threshold_set"]] = r
    sets = sorted({r["threshold_set"] for r in rows})
    out = []
    for (shield, crash), per_set in by.items():
        base = per_set.get(BASE_THRESHOLD_SET)
        if base is None:
            continue
        signs = []
        for s in sets:
            avg = _num((per_set.get(s) or {}).get("avg_pct"))
            signs.append(None if avg is None or avg == 0 else avg > 0)
        consistent = len(sets) == 3 and None not in signs and len(set(signs)) == 1
        sig = sum(1 for s in sets if _num((per_set.get(s) or {}).get("binom_p")) is not None
                  and per_set[s]["binom_p"] < SIGNIFICANCE_P)
        out.append({
            "shield": shield, "crash_type": crash, "n_weeks": base.get("n_weeks"),
            "avg_pct": base.get("avg_pct"), "weeks_up": base.get("weeks_up"),
            "binom_p": base.get("binom_p"),
            "direction_consistent": consistent, "significant_sets": sig,
        })

    def order(r):
        s = SHIELD_ORDER.index(r["shield"]) if r["shield"] in SHIELD_ORDER else len(SHIELD_ORDER)
        return (s, r["crash_type"])
    return sorted(out, key=order)


def _evidence(rows):
    out, count = [], {}
    for r in rows:
        topic = r.get("channel")
        if topic not in EVIDENCE_TOPICS or count.get(topic, 0) >= EVIDENCE_PER_TOPIC:
            continue
        count[topic] = count.get(topic, 0) + 1
        out.append({
            "evidence_id": r.get("evidence_id"), "topic": topic, "publisher": r.get("publisher"),
            "date": _txt(r.get("date")), "trust": r.get("trust"), "source_url": r.get("source_url"),
            "excerpt": str(r.get("excerpt") or "")[:EXCERPT_CHARS],
        })
    return out


def get_portfolio_facts(persona):
    p = _lit(persona)
    subject = "subject_type = 'persona' AND subject = " + p
    got = _run_all({
        "holdings": "SELECT h.ticker AS ticker, h.weight AS weight, s.beta_simple AS beta, s.lo_simple AS lo, "
                    "s.hi_simple AS hi FROM persona_holdings h LEFT JOIN sensitivities s ON h.ticker = s.ticker "
                    "WHERE h.persona = " + p + " ORDER BY h.weight DESC, h.ticker LIMIT 20",
        "risk": "SELECT factor, r2 FROM risk_share WHERE " + subject + " LIMIT 10",
        "facts": "SELECT max_drawdown_pct, CAST(drawdown_peak_date AS varchar) AS peak, "
                 "CAST(drawdown_trough_date AS varchar) AS trough, CAST(recovery_date AS varchar) AS recovery, "
                 "worst_year, worst_year_return_pct, worst_13w_return_pct, "
                 "CAST(worst_13w_end_date AS varchar) AS worst_13w_end, "
                 "dd_us10y_chg_pp, dd_ca10y_chg_pp, dd_brent_chg_pct, dd_xiu_chg_pct, "
                 "w13_us10y_chg_pp, w13_ca10y_chg_pp, w13_brent_chg_pct, w13_xiu_chg_pct "
                 "FROM facts WHERE " + subject + " LIMIT 1",
        "protection": "SELECT stock_side, bond_side, n_worst_weeks, avg_bond_return_pct, avg_stock_return_pct "
                      "FROM protection WHERE subject = " + p + " AND period = 'all' LIMIT 1",
        "crash": "SELECT n_weeks, avg_xiu_pct, avg_us10y_chg_bp, avg_ca10y_chg_bp, avg_brent_pct, "
                 "stock_crash_share, rate_shock_share, crash_type FROM crash_profile WHERE persona = " + p +
                 " LIMIT 1",
        "shields": "SELECT item, label, avg_pct_worst, weeks_up, weeks, binom_p, usd_weight, contribution_pct, "
                   "contribution_per_100k, twin_max_drawdown, actual_max_drawdown FROM shields "
                   "WHERE persona = " + p + " LIMIT 20",
        "matrix": "SELECT threshold_set, shield, crash_type, n_weeks, avg_pct, weeks_up, binom_p "
                  "FROM shield_by_crash_type LIMIT 100",
        "cushion": "SELECT candidate, avg_pct_worst, weeks_up, weeks, binom_p, avg_pct_all, corr_full "
                   "FROM cushion WHERE stock_side = 'XIU.TO' AND candidate IN " + _in_list(CUSHION_CANDIDATES) +
                   " LIMIT 20",
        "links": "SELECT link_id, from_node, to_node, beta, lo, hi, unit FROM links WHERE link_id IN " +
                 _in_list([i for _, i in RATES_LINKS.values()]) + " LIMIT 20",
        "sb_regime": "SELECT pair, measure, correlation, n_weeks, regime, z_diff, p_diff FROM stock_bond "
                     "WHERE measure IN ('cpi_ge_3', 'cpi_lt_3') LIMIT 20",
        "sb_roll": "SELECT pair, CAST(week AS varchar) AS week, correlation FROM stock_bond "
                   "WHERE measure = 'rolling_52w' ORDER BY pair, week LIMIT 1000",
        "weekly": "SELECT subject_or_ticker AS subject, CAST(week AS varchar) AS week, ret_cad FROM weekly_returns "
                  "WHERE subject_or_ticker = " + p + " OR subject_or_ticker LIKE '" + persona +
                  ":%' ORDER BY week LIMIT 1000",
        "evidence": "SELECT evidence_id, channel, publisher, CAST(\"date\" AS varchar) AS \"date\", trust, "
                    "source_url, SUBSTR(excerpt, 1, " + str(EXCERPT_CHARS) + ") AS excerpt FROM evidence "
                    "WHERE ticker = 'macro' AND channel IN " + _in_list(EVIDENCE_TOPICS) +
                    " ORDER BY evidence_id LIMIT 40",
    })

    holdings = got["holdings"]
    held = {h["ticker"] for h in holdings}

    risk_share = {r["factor"]: r["r2"] for r in got["risk"] if r.get("factor") in ("oil", "rates", "stocks")}

    f = _first(got["facts"]) or {}
    facts = None
    if f:
        facts = {
            "max_drawdown_pct": f.get("max_drawdown_pct"),
            "peak_date": f.get("peak"), "trough_date": f.get("trough"),
            "recovery_date": f.get("recovery"), "recovered": f.get("recovery") is not None,
            "worst_year": _txt(f.get("worst_year")), "worst_year_return_pct": f.get("worst_year_return_pct"),
            "worst_13w_return_pct": f.get("worst_13w_return_pct"), "worst_13w_end_date": f.get("worst_13w_end"),
            "market_moves_in_drawdown": {
                "us10y_pp": f.get("dd_us10y_chg_pp"), "ca10y_pp": f.get("dd_ca10y_chg_pp"),
                "brent_pct": f.get("dd_brent_chg_pct"), "xiu_pct": f.get("dd_xiu_chg_pct")},
            "market_moves_in_worst_13w": {
                "us10y_pp": f.get("w13_us10y_chg_pp"), "ca10y_pp": f.get("w13_ca10y_chg_pp"),
                "brent_pct": f.get("w13_brent_chg_pct"), "xiu_pct": f.get("w13_xiu_chg_pct")},
        }

    protection = None
    if held & set(BOND_TICKERS):
        protection = _first(got["protection"])

    shields = sorted(got["shields"], key=lambda r: (
        SHIELD_ORDER.index(r["item"]) if r["item"] in SHIELD_ORDER else len(SHIELD_ORDER), r["item"]))
    twin = next((r["item"] for r in shields if "->" in str(r["item"])), None)

    betas = []
    links = {l["link_id"]: l for l in got["links"]}
    for h in holdings:
        rates = None
        spec = RATES_LINKS.get(h["ticker"])
        link = links.get(spec[1]) if spec else None
        if link and _num(link.get("beta")) is not None:
            rates = {"link": link["link_id"], "beta": link["beta"], "lo": link.get("lo"), "hi": link.get("hi")}
        betas.append({"ticker": h["ticker"], "weight": h["weight"],
                      "oil": {"beta": h.get("beta"), "lo": h.get("lo"), "hi": h.get("hi")}, "rates": rates})

    weekly = {}
    for r in got["weekly"]:
        weekly.setdefault(r["subject"], []).append(r)
    series = {"persona": _drawdown_by_month(weekly.get(persona, []))}
    series["twin"] = _drawdown_by_month(weekly[twin]) if twin and twin in weekly else None
    months = sorted(set(series["persona"]) | set(series["twin"] or {}))
    twin_series = {
        "months": months, "persona": [series["persona"].get(m) for m in months],
        "twin_subject": twin if series["twin"] is not None else None,
        "twin": [series["twin"].get(m) for m in months] if series["twin"] is not None else None,
    }

    regimes = {}
    for r in got["sb_regime"]:
        e = regimes.setdefault(r["pair"], {"regime": r.get("regime"), "z_diff": r.get("z_diff"),
                                           "p_diff": r.get("p_diff")})
        e[r["measure"]] = {"corr": r.get("correlation"), "n_weeks": r.get("n_weeks")}
    roll = {}
    for r in got["sb_roll"]:  # rows come in week order, so the last week of each month wins
        roll.setdefault(r["pair"], {})[_month(r["week"])] = r.get("correlation")
    roll_months = sorted({m for v in roll.values() for m in v})
    stock_bond = {
        "by_cpi_regime": regimes,
        "rolling_52w_monthly": dict({"months": roll_months},
                                    **{pair: [roll[pair].get(m) for m in roll_months] for pair in sorted(roll)}),
        "cpi_regime": None,
        "cpi_regime_note": "the weekly CPI regime flag is not stored in the processed tables, so it is not "
                           "available per month; the full-sample correlations by regime are in by_cpi_regime",
    }

    cushion = sorted(got["cushion"], key=lambda r: CUSHION_CANDIDATES.index(r["candidate"])
                     if r["candidate"] in CUSHION_CANDIDATES else len(CUSHION_CANDIDATES))

    return {
        "persona": persona,
        "window": FACTS_WINDOW,
        "risk_share": risk_share,
        "facts": facts,
        "protection": protection,
        "crash_profile": _first(got["crash"]),
        "shields": shields,
        "shield_matrix": _shield_matrix(got["matrix"]),
        "cushion_top": cushion,
        "betas": betas,
        "twin_series": twin_series,
        "stock_bond": stock_bond,
        "evidence": _evidence(got["evidence"]),
        "units": "all returns weekly, CAD, simple, in %; " + FACTS_NOTE + ". risk_share: r2 of three separate "
                 "single-factor regressions (oil, rates, stocks); they overlap and do not add up. facts: "
                 "market_moves_* = yield changes in pp, Brent and XIU.TO in % over the drawdown (peak to "
                 "trough) and over the worst 13 weeks. protection: pooled average bond-side return in the "
                 "bottom 10% stock weeks. shields: persona's worst 10% weeks, see test_shield for labels. "
                 "shield_matrix: market-level, threshold set -2/+10; direction_consistent = same sign of "
                 "avg_pct at all 3 threshold sets; significant_sets = number of sets (of 3) with binom_p < "
                 "0.05. betas: oil beta from sensitivities (% per 1% Brent, weekly, CAD) and rates beta from "
                 "links (log return per 1 pp yield change), each with 95% range. twin_series: deepest "
                 "drawdown % within each month, persona and hedged twin aligned on months. stock_bond: "
                 "correlation of stock and bond funds; rolling_52w_monthly = value at the last week of each "
                 "month. evidence: research excerpts, up to 400 characters.",
    }


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


def _round(x, digits=3):
    if isinstance(x, float):
        r = round(x, digits)
        return int(r) if r.is_integer() else r   # counts arrive as floats from _convert
    if isinstance(x, dict):
        return {k: _round(v, digits) for k, v in x.items()}
    if isinstance(x, list):
        return [_round(v, digits) for v in x]
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
        kind = norm_shock_type(params.get("shock_type"))
        if kind == "rates":
            _require(params, ["persona", "rates_shock_bp"])
            p = norm_persona(params["persona"])
            bp = norm_rates_bp(params["rates_shock_bp"])
            return (fn, "rates", p, bp), lambda: run_scenario_rates(p, bp)
        _require(params, ["persona", "oil_shock_pct"])
        p = norm_persona(params["persona"])
        s = norm_shock(params["oil_shock_pct"])
        return (fn, p, s), lambda: run_scenario(p, s)
    if fn == "get_portfolio_facts":
        _require(params, ["persona"])
        p = norm_persona(params["persona"])
        return (fn, p), lambda: get_portfolio_facts(p)
    if fn == "test_shield":
        _require(params, ["ticker", "persona"])
        p = norm_persona(params["persona"])
        t = norm_shield(params["ticker"])
        return (fn, p, t), lambda: test_shield(p, t)
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
        digits = FACTS_DIGITS if fn == "get_portfolio_facts" or result.get("shock_type") == "rates" else 3
        result = _fit(_round(result, digits))
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
