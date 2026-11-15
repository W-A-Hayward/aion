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
        max_tokens=1500,
    )


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
    system_prompt = "%s\nPersona: %s\nLevel: %s" % (_get_instructions(), persona, level)
    agent = Agent(model=_build_model(), tools=TOOLS, system_prompt=system_prompt)
    result = agent(question)
    with _lock:
        calls = list(_tool_calls)
        citations = list(_citations)
    return {"answer": str(result), "toolCalls": calls, "citations": citations, "usage": _usage(result)}


if __name__ == "__main__":
    app.run()
