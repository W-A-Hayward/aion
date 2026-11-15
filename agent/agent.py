"""cascade agent: Strands Agent on Amazon Bedrock AgentCore Runtime.

Tools call the cascade-tools Lambda (action group "oil-tools") and the cascade-evidence knowledge base.
Payload: {"question": str, "persona": str, "level": str}.
"""
import json
import os
import threading

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


def _record_call(name, inputs, output):
    with _lock:
        _tool_calls.append({"name": name, "input": inputs, "output": _truncate(output)})


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
    _record_call(name, params, result)
    _record_claims(name, params, result)
    return result


# ----------------------------------------------------------------------------- tools

@tool
def get_portfolio_exposure(persona: str) -> dict:
    """Call first on every question. Returns the persona's holdings, weights, oil beta with 95% range,
    each holding's contribution and the portfolio-level beta.

    Args:
        persona: Persona name. Allowed values: robert, amira, mateo.
    """
    return _call_tools_lambda("get_portfolio_exposure", persona=persona)


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
def run_scenario(persona: str, oil_shock_pct: str) -> dict:
    """Call when the user asks "what if oil moves X%". Returns the estimated impact with 95% range for the
    persona's portfolio and for each holding. Only the four listed shocks are supported.

    Args:
        persona: Persona name. Allowed values: robert, amira, mateo.
        oil_shock_pct: Brent oil move in percent. Allowed values: -30, -15, 15, 30.
    """
    return _call_tools_lambda("run_scenario", persona=persona, oil_shock_pct=oil_shock_pct)


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
    try:
        response = _kb().retrieve(
            knowledgeBaseId=KB_ID,
            retrievalQuery={"text": query},
            retrievalConfiguration=config,
        )
    except Exception as e:
        out = {"error": "search failed: %s" % type(e).__name__}
        _record_call("search_evidence", inputs, out)
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
    _record_call("search_evidence", inputs, rows)
    return rows


TOOLS = [
    get_portfolio_exposure, get_asset_sensitivity, explain_channel,
    run_scenario, compare_alternative, get_validation, search_evidence,
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
        max_tokens=1500,
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
    with _lock:
        _tool_calls.clear()
        _citations.clear()
        _claims.clear()
        _guardrail_traces.clear()
    system_prompt = "%s\nPersona: %s\nLevel: %s" % (_get_instructions(), persona, level)
    agent = Agent(model=_build_model(), tools=TOOLS, system_prompt=system_prompt,
                  callback_handler=_on_stream_event)
    result = agent(question)
    with _lock:
        calls = list(_tool_calls)
        citations = list(_citations)
        claims = list(_claims)
        traces = list(_guardrail_traces)
    out = {"answer": str(result), "toolCalls": calls, "citations": citations, "claims": claims,
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
