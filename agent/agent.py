"""cascade agent: Strands Agent on Amazon Bedrock AgentCore Runtime.

Tools call the cascade-tools Lambda (action group "oil-tools") and the cascade-evidence knowledge base.
Payload: {"persona": str, "question": str, "level": str, "experiment_id": str (optional)}.
The level goes into the system prompt. experiment_id is accepted and ignored here: the worker uses it
for its answer cache.
Returns {"answer_text", "trace", "tool_results"}, plus the keys the worker, eval and smoke test already read
(answer, toolCalls, citations, claims, usage, guardrail).
  trace: one {step, tool, input_summary, output_summary, tag, ms} per tool call; tag is "measured" for the
         Athena tools and "source" for the knowledge base.
  tool_results: {tool name: [raw JSON result of each call, in call order]}.
"""
import json
import os
import re
import threading
import time

import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent, tool
from strands.models import BedrockModel

MODEL_ID = os.environ.get("MODEL_ID", "global.anthropic.claude-sonnet-5-5")
TOOLS_FUNCTION = os.environ.get("TOOLS_FUNCTION", "cascade-tools")
KB_ID = os.environ.get("KB_ID") or None
GUARDRAIL_ID = os.environ.get("GUARDRAIL_ID") or None
GUARDRAIL_VERSION = os.environ.get("GUARDRAIL_VERSION") or None
BUCKET = os.environ.get("BUCKET", "cascade-s3-bucket")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

ACTION_GROUP = "oil-tools"
PROMPT_KEY = "prompts/agent_instructions.md"
MAX_OUTPUT_CHARS = 1500

app = BedrockAgentCoreApp()

_instructions = None
_lambda_client = None
_kb_client = None

# Per-request records. Reset at the start of each invoke; the lock guards parallel tool threads.
_lock = threading.Lock()
_tool_calls = []
_citations = []
_claims = []
_guardrail_traces = []
_trace = []
_request = {"holdings": None}  # the current request's custom holdings, if any
_tool_results = {}

KB_TOOLS = ("search_evidence",)  # tag "source"; every other tool reads Athena through cascade-tools: "measured"


# ----------------------------------------------------------------------------- helpers

def _get_instructions():
    global _instructions
    if _instructions is None:
        s3 = boto3.client("s3", region_name=AWS_REGION)
        obj = s3.get_object(Bucket=BUCKET, Key=PROMPT_KEY)
        _instructions = obj["Body"].read().decode("utf-8")
    return _instructions


def _lambda():
    global _lambda_client
    if _lambda_client is None:
        _lambda_client = boto3.client("lambda", region_name=AWS_REGION)
    return _lambda_client


def _kb():
    global _kb_client
    if _kb_client is None:
        _kb_client = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)
    return _kb_client


def _truncate(value):
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= MAX_OUTPUT_CHARS else text[:MAX_OUTPUT_CHARS] + "...[truncated]"


def _fmt(value, digits=2, signed=True):
    value = _number(value)
    if value is None:
        return "n/a"
    return ("%+." if signed else "%.") + str(digits) + "f" % value


def _summarize_input(inputs):
    if not isinstance(inputs, dict):
        return ""
    return ", ".join("%s=%s" % (k, v) for k, v in inputs.items() if v is not None)


def _summarize_output(name, result):
    """Key numbers of one tool result as a short string (never the model's text)."""
    if isinstance(result, list):
        if result and isinstance(result[0], dict) and result[0].get("error"):
            return "error: %s" % result[0]["error"]
        return "%d passages" % len(result)
    if not isinstance(result, dict):
        return "ok"
    if result.get("error"):
        return "error: %s" % result["error"]

    def box(source, key):
        value = source.get(key)
        return value if isinstance(value, dict) else {}

    parts = []
    if name == "get_portfolio_facts":
        prot = box(result, "protection")
        if prot:
            parts.append("bonds avg %s%% in %s worst weeks of %s" % (
                _fmt(prot.get("avg_bond_return_pct")), prot.get("n_worst_weeks"), prot.get("stock_side")))
        risk = box(result, "risk_share")
        if risk:
            parts.append("risk_share " + ", ".join(
                "%s %s" % (k, _fmt(risk.get(k), 3, False)) for k in ("rates", "stocks", "oil") if k in risk))
        facts = box(result, "facts")
        if facts.get("max_drawdown_pct") is not None:
            parts.append("max drawdown %s%%" % _fmt(facts.get("max_drawdown_pct")))
    elif name == "test_shield":
        row = box(result, "worst_weeks")
        if row:
            parts.append("%s %s: avg %s%% in %s worst weeks, %s up, p=%s" % (
                result.get("ticker"), row.get("label"), _fmt(row.get("avg_pct_worst")), row.get("weeks"),
                row.get("weeks_up"), _fmt(row.get("binom_p"), 3, False)))
        else:
            parts.append("%s: no row for this persona" % result.get("ticker"))
    elif name == "run_scenario":
        if result.get("shock_type") == "rates":
            total = box(result, "total")
            parts.append("rates %sbp: total %s%% (%s per $100k)" % (
                result.get("rates_shock_bp"), _fmt(total.get("impact_pct")), _fmt(total.get("per_100k"), 0)))
        else:
            rows = [r for r in (result.get("scenario") or []) if isinstance(r, dict)]
            if rows:
                r = rows[0]
                parts.append("oil %s%%: %s%% (95%% %s to %s)" % (
                    result.get("oil_shock_pct"), _fmt(r.get("impact_pct")), _fmt(r.get("lo_pct")),
                    _fmt(r.get("hi_pct"))))
    elif name == "get_portfolio_exposure":
        parts.append("portfolio beta %s" % _fmt(box(result, "portfolio_beta").get("beta")))
    elif name == "get_asset_sensitivity":
        parts.append("%s beta %s" % (result.get("ticker"), _fmt(box(result, "sensitivity").get("beta_simple"))))
    elif name == "explain_channel":
        parts.append("%s channel label %s" % (result.get("ticker"), box(result, "confidence").get("label")))
    elif name == "get_validation":
        v = box(result, "validation")
        parts.append("%s label %s, ex-2022 beta %s" % (result.get("ticker"), v.get("label"),
                                                      _fmt(v.get("beta_ex2022"))))
    elif name == "compare_alternative":
        c = box(result, "comparison")
        parts.append("30%% oil impact %s%% before, %s%% after" % (
            _fmt(c.get("impact30_before_pct")), _fmt(c.get("impact30_after_pct"))))
    return "; ".join(parts) or "ok"


def _record_call(name, inputs, output, ms=0):
    try:
        summary = _summarize_output(name, output)
    except Exception:  # a summary must never break the run
        summary = "ok"
    with _lock:
        _tool_calls.append({"name": name, "input": inputs, "output": _truncate(output)})
        _tool_results.setdefault(name, []).append(output)
        _trace.append({
            "step": len(_trace) + 1,
            "tool": name,
            "input_summary": _summarize_input(inputs),
            "output_summary": summary,
            "tag": "source" if name in KB_TOOLS else "measured",
            "ms": int(ms),
        })


def _record_citation(row):
    if not isinstance(row, dict):
        return
    with _lock:
        _citations.append({
            "text": row.get("text") if row.get("text") is not None else row.get("excerpt"),
            "source_url": row.get("source_url"),
            "section": row.get("section"),
            "ticker": row.get("ticker"),
            "channel": row.get("channel"),
        })


def _number(value):
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and value == value
    return value if ok else None


def _text(value):
    return value if isinstance(value, str) and value else None


def claims_from_result(name, params, result):
    """Structured claims taken from one tool result (never from the model's prose).

    Each claim is {"ticker" | "persona": str, "label"?, "beta"?, "verdict"?, "impact_pct"?}. Scenario
    claims also carry "shock_pct", because impact_pct means nothing without it. A result with an
    "error" gives no claims. Keep in step with eval/claims.py, which rebuilds claims from stored
    tool calls.
    """
    if not isinstance(result, dict) or result.get("error"):
        return []
    params = params if isinstance(params, dict) else {}
    ticker = result.get("ticker") or params.get("ticker")
    persona = result.get("persona") or params.get("persona")
    out = []

    def add(key, subject, **fields):
        fields = {k: v for k, v in fields.items() if v is not None}
        if subject and fields:
            out.append(dict({key: subject}, **fields))

    def rows(key):
        return [r for r in (result.get(key) or []) if isinstance(r, dict)]

    def box(key):
        value = result.get(key)
        return value if isinstance(value, dict) else {}

    if name == "get_portfolio_exposure":
        for h in rows("holdings"):
            add("ticker", h.get("ticker"), beta=_number(h.get("beta")))
        add("persona", persona, beta=_number(box("portfolio_beta").get("beta")))
    elif name == "get_asset_sensitivity":
        add("ticker", ticker, beta=_number(box("sensitivity").get("beta_simple")))
    elif name == "explain_channel":
        add("ticker", ticker, label=_text(box("confidence").get("label")))
    elif name == "get_validation":
        add("ticker", ticker, label=_text(box("validation").get("label")))
    elif name == "run_scenario":
        shock = _number(result.get("oil_shock_pct"))
        shock = int(shock) if shock is not None and shock == int(shock) else shock
        for s in rows("scenario"):
            add("persona", persona, impact_pct=_number(s.get("impact_pct")), shock_pct=shock)
        for h in rows("holding_impacts"):
            add("ticker", h.get("ticker"), impact_pct=_number(h.get("impact_pct")), shock_pct=shock)
    elif name == "compare_alternative":
        c = box("comparison")
        add("ticker", result.get("holding"), beta=_number(c.get("beta_holding")))
        add("ticker", result.get("alternative"), beta=_number(c.get("beta_alternative")))

    # A verdict (for example from a materiality table) at the top level or one level down.
    for holder in [result] + [v for v in result.values() if isinstance(v, dict)]:
        verdict = _text(holder.get("verdict"))
        if verdict:
            if ticker:
                add("ticker", ticker, verdict=verdict)
            else:
                add("persona", persona, verdict=verdict)
    return out


def _record_claims(name, params, result):
    new = claims_from_result(name, params, result)
    with _lock:
        for claim in new:
            if claim not in _claims:  # deduplicate
                _claims.append(claim)


def _call_tools_lambda(name, **params):
    """Invoke cascade-tools in the Bedrock-Agent event format; return the parsed JSON body."""
    event = {
        "messageVersion": "1.0",
        "actionGroup": ACTION_GROUP,
        "function": name,
        "parameters": [{"name": k, "type": "string", "value": str(v)} for k, v in params.items()],
    }
    started = time.time()
    try:
        response = _lambda().invoke(
            FunctionName=TOOLS_FUNCTION,
            InvocationType="RequestResponse",
            Payload=json.dumps(event).encode("utf-8"),
        )
        payload = response["Payload"]
        raw = payload.read() if hasattr(payload, "read") else payload
        outer = json.loads(raw)
        body = outer["response"]["functionResponse"]["responseBody"]["TEXT"]["body"]
        result = json.loads(body)
    except Exception as e:  # return the failure to the model instead of crashing the run
        result = {"error": "tool call failed: %s" % type(e).__name__, "allowed": []}
    _record_call(name, params, result, (time.time() - started) * 1000)
    _record_claims(name, params, result)
    return result


# ----------------------------------------------------------------------------- tools

def _clean_holdings(raw):
    """Holdings validated by lambdas/submit; re-checked here so the system prompt only carries clean text."""
    if not isinstance(raw, list):
        return None
    out = []
    for row in raw[:14]:
        t = row.get("ticker") if isinstance(row, dict) else None
        w = row.get("weight") if isinstance(row, dict) else None
        if not (isinstance(t, str) and re.fullmatch(r"[A-Z0-9.]{1,10}", t)):
            return None
        if isinstance(w, bool) or not isinstance(w, (int, float)) or not 0 < w <= 1:
            return None
        out.append({"ticker": t, "weight": float(w)})
    return out or None


def _portfolio_params(persona):
    """Tool parameters for a portfolio: the custom holdings are attached when persona is custom."""
    if str(persona).strip().lower() == "custom" and _request["holdings"]:
        return {"persona": "custom", "holdings": json.dumps(_request["holdings"])}
    return {"persona": persona}


def custom_portfolio_prompt(holdings):
    mix = ", ".join("%s %s%%" % (h["ticker"], ("%.1f" % (h["weight"] * 100)).rstrip("0").rstrip(".")) for h in holdings)
    return ("\nPortfolio: custom, the user's own holdings: %s.\n"
            "For this portfolio pass persona \"custom\" to get_portfolio_exposure and run_scenario; the holdings "
            "are attached automatically. get_portfolio_facts, test_shield, compare_alternative and rates scenarios are not available for a custom portfolio (their tables are built per sample persona); say so if asked. Its portfolio "
            "beta is the weighted sum of each holding's beta, a proxy with no range: say so once, and do not "
            "describe it as measured on the portfolio itself. Ignore PERSONA FOCUS." % mix)



@tool
def get_portfolio_exposure(persona: str) -> dict:
    """Call first on every question. Returns the persona's holdings, weights, oil beta with 95% range,
    each holding's contribution and the portfolio-level beta.

    Args:
        persona: Persona name. Allowed values: robert, amira, mateo, custom (the user's own portfolio).
    """
    return _call_tools_lambda("get_portfolio_exposure", **_portfolio_params(persona))


@tool
def get_asset_sensitivity(ticker: str) -> dict:
    """Call to get one ticker's oil beta (simple and market-controlled), 95% range, p-values and recent
    52-week rolling beta. Use for a holding or an asset the user names.

    Args:
        ticker: Ticker symbol. Allowed values: XIU.TO, ENB.TO, XOM, TLT, XBB.TO, ZST.TO, QQQ, SHOP.TO, SPY,
            VFV.TO, XSP.TO, XESG.TO, ATD.TO, RY.TO, CNQ.TO, CNR.TO, FTS.TO, TD.TO, MFC.TO, CSU.TO, NVDA,
            AAPL, MSFT, GOOGL, AMZN, TSLA, JPM, JNJ, PG, GLD, AGG, ESGV, XRB.TO, XLB.TO, XEG.TO.
    """
    return _call_tools_lambda("get_asset_sensitivity", ticker=ticker)


@tool
def explain_channel(ticker: str) -> dict:
    """Call for a holding that matters to explain how oil reaches it (direct, rates, currency). Returns the
    confidence label, chain steps, duration check and cited evidence with section.

    Args:
        ticker: Ticker symbol. Allowed values: XIU.TO, ENB.TO, XOM, TLT, XBB.TO, ZST.TO, QQQ, SHOP.TO, SPY,
            VFV.TO, XSP.TO, XESG.TO, ATD.TO, RY.TO, CNQ.TO, CNR.TO, FTS.TO, TD.TO, MFC.TO, CSU.TO, NVDA,
            AAPL, MSFT, GOOGL, AMZN, TSLA, JPM, JNJ, PG, GLD, AGG, ESGV, XRB.TO, XLB.TO, XEG.TO.
    """
    result = _call_tools_lambda("explain_channel", ticker=ticker)
    if isinstance(result, dict):
        for row in result.get("evidence") or []:
            _record_citation(row)
    return result


@tool
def run_scenario(persona: str, oil_shock_pct: str = None, shock_type: str = "oil",
                 rates_shock_bp: str = None) -> dict:
    """Call when the user asks "what if oil moves X%" (shock_type oil) or "what if interest rates rise or
    fall X bp" (shock_type rates). Oil: returns the estimated impact with 95% range for the persona's
    portfolio and for each holding; only the four listed oil shocks are supported. Rates: moves the US 10y
    and Canada 10y yields (and the Canada 2y for ZST.TO) by the same number of basis points through the
    measured yield links; returns per-holding % impact, dollars per $100,000, the total, the links used
    with their 95% ranges, and the holdings that have no measured rates link (not_linked, left out of the
    total).

    Args:
        persona: Persona name. Allowed values: robert, amira, mateo, custom (the user's own portfolio; oil only).
        oil_shock_pct: Brent oil move in percent, for shock_type oil. Allowed values: -30, -15, 15, 30.
        shock_type: Allowed values: oil (default), rates.
        rates_shock_bp: Yield move in basis points, for shock_type rates, for example 100 or -50. A non-zero
            whole number between -300 and 300.
    """
    params = dict(_portfolio_params(persona))
    if shock_type and str(shock_type).strip().lower() != "oil":
        params["shock_type"] = shock_type
        params["rates_shock_bp"] = rates_shock_bp
    else:
        params["oil_shock_pct"] = oil_shock_pct
    return _call_tools_lambda("run_scenario", **{k: v for k, v in params.items() if v is not None})


@tool
def get_portfolio_facts(persona: str) -> dict:
    """Call for questions about how the portfolio behaved in bad times, not just about oil: crash history
    (max drawdown with peak, trough and recovery dates, worst year, worst 13 weeks, and what oil, yields and
    stocks did meanwhile), what drives the risk (oil, rates, stocks r2), whether the bond side protected in
    the worst stock weeks, the persona's crash profile, which external shields (usdcad, GLD, ZST.TO, XBB.TO,
    AGG, TLT_usd) worked, the shield matrix by crash type with threshold-robustness flags, the best
    cushions for a stock-side crash, per-holding oil and rates betas with 95% ranges, monthly drawdown of
    the persona and its hedged twin, the stock-bond correlation by CPI regime and over time, and research
    evidence on currency and stock-bond with publisher, date, trust tier and source. 2021-2026 only; past
    behaviour; descriptive.

    Args:
        persona: Persona name. Allowed values: robert, amira, mateo.
    """
    return _call_tools_lambda("get_portfolio_facts", persona=persona)


@tool
def test_shield(ticker: str, persona: str) -> dict:
    """Call when the user asks whether a given asset would have cushioned the persona's worst weeks. Returns
    that ticker's average return, weeks up, weeks, binomial p-value and label (WORKING, BROKEN, NEUTRAL,
    HIDDEN, REMOVED) in the persona's worst 10% portfolio weeks, plus the ticker's results by crash type
    (stock_crash, rate_shock, other) at three threshold sets when available. Unknown tickers return
    "not in universe". 2021-2026 only; past behaviour; descriptive.

    Args:
        ticker: Ticker symbol from the universe (for example GLD, AGG, ZST.TO, XBB.TO, SPY, XIU.TO) or the
            shield names usdcad and TLT_usd.
        persona: Persona name. Allowed values: robert, amira, mateo.
    """
    return _call_tools_lambda("test_shield", ticker=ticker, persona=persona)


@tool
def compare_alternative(persona: str, holding: str, alternative: str) -> dict:
    """Call when the user asks "what instead" about swapping a holding. Returns both betas and the portfolio
    impact of a +30% oil move before and after. Only the listed swaps are supported.

    Args:
        persona: Persona name. Allowed values: robert, amira, mateo.
        holding: Current holding. Allowed values by persona: robert: TLT or XBB.TO; mateo: XIU.TO or VFV.TO;
            amira: QQQ.
        alternative: Replacement ticker. Allowed pairs (persona holding to alternative): robert TLT to ZST.TO;
            robert XBB.TO to ZST.TO; mateo XIU.TO to XESG.TO; mateo VFV.TO to XSP.TO; amira QQQ to XIU.TO.
    """
    return _call_tools_lambda("compare_alternative", persona=persona, holding=holding, alternative=alternative)


@tool
def get_validation(ticker: str) -> dict:
    """Call for a holding that matters to check robustness. Returns the ex-2022 beta with range, the
    out-of-sample hit rate, the beta in oil-up and oil-down weeks, and the green/yellow/grey label.

    Args:
        ticker: Ticker symbol. Allowed values: XIU.TO, ENB.TO, XOM, TLT, XBB.TO, ZST.TO, QQQ, SHOP.TO, SPY,
            VFV.TO, XSP.TO, XESG.TO, ATD.TO, RY.TO, CNQ.TO, CNR.TO, FTS.TO, TD.TO, MFC.TO, CSU.TO, NVDA,
            AAPL, MSFT, GOOGL, AMZN, TSLA, JPM, JNJ, PG, GLD, AGG, ESGV, XRB.TO, XLB.TO, XEG.TO.
    """
    return _call_tools_lambda("get_validation", ticker=ticker)


@tool
def search_evidence(query: str, ticker: str = None) -> list:
    """Search the evidence knowledge base (filings, issuer documents, macro notes) for passages that support
    a claim about how oil affects an asset. Call after the numeric tools when a claim needs a source. Returns
    up to 3 passages with text, source_url, section, ticker and channel; cite them.

    Args:
        query: Short natural-language search text, for example "pipeline tariffs oil price sensitivity".
        ticker: Optional ticker to restrict results to one asset, for example ENB.TO. Omit to search all.
    """
    config = {"vectorSearchConfiguration": {"numberOfResults": 3}}
    if ticker:
        config["vectorSearchConfiguration"]["filter"] = {"equals": {"key": "ticker", "value": ticker}}
    inputs = {"query": query, "ticker": ticker}
    started = time.time()
    try:
        response = _kb().retrieve(
            knowledgeBaseId=KB_ID,
            retrievalQuery={"text": query},
            retrievalConfiguration=config,
        )
    except Exception as e:
        out = {"error": "search failed: %s" % type(e).__name__}
        _record_call("search_evidence", inputs, out, (time.time() - started) * 1000)
        return [out]
    rows = []
    for r in response.get("retrievalResults", [])[:3]:
        meta = r.get("metadata") or {}
        loc = r.get("location") or {}
        source_url = meta.get("source_url") or (loc.get("webLocation") or {}).get("url") \
            or (loc.get("s3Location") or {}).get("uri")
        row = {
            "text": (r.get("content") or {}).get("text"),
            "source_url": source_url,
            "section": meta.get("section"),
            "ticker": meta.get("ticker"),
            "channel": meta.get("channel"),
        }
        rows.append(row)
        _record_citation(row)
    _record_call("search_evidence", inputs, rows, (time.time() - started) * 1000)
    return rows


TOOLS = [
    get_portfolio_exposure, get_asset_sensitivity, explain_channel,
    run_scenario, compare_alternative, get_validation, get_portfolio_facts, test_shield, search_evidence,
]


# ----------------------------------------------------------------------------- entrypoint

def _build_model():
    return BedrockModel(
        model_id=MODEL_ID,
        region_name=AWS_REGION,
        guardrail_id=GUARDRAIL_ID,
        guardrail_version=GUARDRAIL_VERSION,
        guardrail_trace="enabled",
        guardrail_latest_message=True,  # evaluate only the latest user message, not the system prompt/history
        max_tokens=4096,
    )


_FIRED = ("BLOCKED", "ANONYMIZED")


def _fired(items):
    return [i for i in (items or []) if isinstance(i, dict) and i.get("action") in _FIRED]


def _summarize_assessment(a):
    """Policies that fired in one guardrail assessment dict (Converse trace or apply_guardrail)."""
    out = {}
    topics = [t.get("name") for t in _fired((a.get("topicPolicy") or {}).get("topics"))]
    filters = [f.get("type") for f in _fired((a.get("contentPolicy") or {}).get("filters"))]
    wp = a.get("wordPolicy") or {}
    words = [w.get("match") for w in _fired(wp.get("customWords")) + _fired(wp.get("managedWordLists"))]
    sp = a.get("sensitiveInformationPolicy") or {}
    entities = [e.get("type") for e in _fired(sp.get("piiEntities"))]
    entities += [r.get("name") for r in _fired(sp.get("regexes"))]
    grounding = [
        {"type": f.get("type"), "score": f.get("score"), "threshold": f.get("threshold")}
        for f in _fired((a.get("contextualGroundingPolicy") or {}).get("filters"))
    ]
    for key, value in (("topics", topics), ("content_filters", filters), ("words", words),
                       ("sensitive_information", entities), ("contextual_grounding", grounding)):
        if value:
            out[key] = value
    return out


def summarize_guardrail(trace, source=None):
    """Which guardrail policies fired. `trace` is the Converse trace["guardrail"] dict, or an
    apply_guardrail response (pass `source`="INPUT"/"OUTPUT" for the latter).
    Returns a list of {"source", topics, content_filters, words, sensitive_information,
    contextual_grounding} records, one per source, containing only the policies that fired."""
    if not isinstance(trace, dict):
        return []
    pairs = []
    for a in (trace.get("inputAssessment") or {}).values():
        pairs.append(("INPUT", a))
    for lst in (trace.get("outputAssessments") or {}).values():
        for a in lst or []:
            pairs.append(("OUTPUT", a))
    for a in trace.get("assessments") or []:
        pairs.append((source or trace.get("source"), a))
    merged = {}
    for src, a in pairs:
        if not isinstance(a, dict):
            continue
        for key, value in _summarize_assessment(a).items():
            rec = merged.setdefault(src, {"source": src})
            rec.setdefault(key, []).extend(value)
    return list(merged.values())


def _on_stream_event(**kwargs):
    """Strands callback: collect guardrail traces from raw model stream metadata."""
    ev = kwargs.get("event")
    if not isinstance(ev, dict):
        return
    meta = ev.get("metadata")
    trace = ((meta or {}).get("trace") or {}).get("guardrail") if isinstance(meta, dict) else None
    if trace:
        with _lock:
            _guardrail_traces.append(trace)


def _usage(result):
    metrics = getattr(result, "metrics", None)
    usage = getattr(metrics, "accumulated_usage", None) if metrics is not None else None
    return dict(usage) if isinstance(usage, dict) else {}


@app.entrypoint
def invoke(payload):
    payload = payload if isinstance(payload, dict) else {}
    question = str(payload.get("question") or "")
    persona = str(payload.get("persona") or "")
    level = str(payload.get("level") or "")
    holdings = _clean_holdings(payload.get("holdings")) if persona == "custom" else None
    with _lock:
        _tool_calls.clear()
        _citations.clear()
        _claims.clear()
        _guardrail_traces.clear()
        _trace.clear()
        _tool_results.clear()
        _request["holdings"] = holdings
    system_prompt = "%s\nPersona: %s\nLevel: %s" % (_get_instructions(), persona, level)
    if holdings:
        system_prompt += custom_portfolio_prompt(holdings)
    agent = Agent(model=_build_model(), tools=TOOLS, system_prompt=system_prompt,
                  callback_handler=_on_stream_event)
    result = agent(question)
    with _lock:
        calls = list(_tool_calls)
        citations = list(_citations)
        claims = list(_claims)
        traces = list(_guardrail_traces)
        trace = [dict(t) for t in _trace]
        tool_results = {k: list(v) for k, v in _tool_results.items()}
    answer = str(result)
    out = {"answer_text": answer, "trace": trace, "tool_results": tool_results,
           "answer": answer, "toolCalls": calls, "citations": citations, "claims": claims,
           "usage": _usage(result)}
    records = []
    for trace in traces:
        records.extend(summarize_guardrail(trace))
    if records:
        out["guardrail"] = records
        print(json.dumps({"guardrail": records}, default=str))
    return out


if __name__ == "__main__":
    app.run()
