import json
import os
import re
import time
from decimal import Decimal
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

MAX_TOOL_CALLS = 20
MAX_CITATIONS = 10
MAX_ANSWER = 100_000
MAX_TOOL_RESPONSE = 1000
MAX_PARAM_VALUE = 500
MAX_EXCERPT = 500
MAX_SUMMARY = 300
MAX_HEADLINE = 300
MIN_SESSION_ID = 33
# A RUNNING job older than this is assumed orphaned by a crashed worker and may be reclaimed.
# Keep it above the Lambda timeout so a live invocation is never claimed twice.
STALE_RUNNING_SECONDS = int(os.environ.get("STALE_RUNNING_SECONDS", "1200"))
THROTTLE_CODES = {
    "ThrottlingException",
    "throttlingException",
    "TooManyRequestsException",
    "ProvisionedThroughputExceededException",
    "RequestLimitExceeded",
    "ServiceUnavailableException",
}

# docs/api_contract.md
VERDICTS = ("NOT LINKED", "MATERIAL", "WORKING", "REMOVED", "BROKEN", "HIDDEN", "MINOR", "MYTH", "REAL")
VERDICT_RE = re.compile(r"(%s)(?![A-Za-z0-9])" % "|".join(VERDICTS))
# Characters skipped before the verdict word: markdown (* _ # >), punctuation (. :), dashes and whitespace.
VERDICT_STRIP = " \t\r\n*_#>.:—–"
DECLINE_MARKER = "[[DECLINE]]"
CAVEAT = "2021–2026 · passé · simulation · pas un conseil"
EVIDENCE_REF_RE = re.compile(r"\[([^\[\]\n]+)\]")
SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+|\n")
GUARDRAIL_POLICIES = ("topics", "content_filters", "words", "contextual_grounding")
CACHE_PREFIX = "cache#"  # cache items live in the jobs table; the key never parses as a job UUID

_clients = {}


def _table():
    if "table" not in _clients:
        _clients["table"] = boto3.resource("dynamodb").Table(os.environ["JOBS_TABLE"])
    return _clients["table"]


def _agent():
    if "agent" not in _clients:
        _clients["agent"] = boto3.client("bedrock-agentcore")
    return _clients["agent"]


def _s3():
    if "s3" not in _clients:
        _clients["s3"] = boto3.client("s3")
    return _clients["s3"]


def trunc(s, n):
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[: n - 3] + "..."


def _error_code(exc):
    if isinstance(exc, ClientError):
        return exc.response.get("Error", {}).get("Code", "")
    return ""


def _json_default(o):
    if isinstance(o, Decimal):
        return float(o)
    return str(o)


def session_id_for(session_id):
    """AgentCore runtime session ids must be at least 33 characters."""
    return ("cascade-" + str(session_id)).ljust(MIN_SESSION_ID, "-")


def read_body(resp):
    """Read the invoke_agent_runtime response body and parse it as JSON (floats as Decimal for DynamoDB)."""
    body = resp["response"]
    raw = body.read() if hasattr(body, "read") else body
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        data = json.loads(raw, parse_float=Decimal)
    except ValueError:
        return {"answer": raw}
    return data if isinstance(data, dict) else {"answer": data}


def _list(value):
    return value if isinstance(value, list) else []


def _dict(value):
    return value if isinstance(value, dict) else {}


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stage(name):
    return {"stage": name, "t": _now()}


def _log(job_id, status, started):
    print(json.dumps({"jobId": job_id, "status": status, "durationMs": int((time.time() - started) * 1000)}))


def _set_status(job_id, status, stages=None, **fields):
    """Set the job status and fields; `stages` (list of stage names) are appended to the stage list."""
    names = {"#s": "status"}
    values = {":s": status}
    sets = ["#s = :s"]
    for i, (k, v) in enumerate(fields.items()):
        names["#f%d" % i] = k
        values[":v%d" % i] = v
        sets.append("#f%d = :v%d" % (i, i))
    if stages:
        names["#stg"] = "stages"
        values[":stg"] = [_stage(n) for n in stages]
        values[":empty"] = []
        sets.append("#stg = list_append(if_not_exists(#stg, :empty), :stg)")
    _table().update_item(
        Key={"jobId": job_id},
        UpdateExpression="SET " + ", ".join(sets),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def _add_stages(job_id, names):
    """Append stages without touching the status."""
    _table().update_item(
        Key={"jobId": job_id},
        UpdateExpression="SET #stg = list_append(if_not_exists(#stg, :empty), :stg)",
        ExpressionAttributeNames={"#stg": "stages"},
        ExpressionAttributeValues={":stg": [_stage(n) for n in names], ":empty": []},
    )


# ----------------------------------------------------------------------------- answer parsing

def parse_answer(text):
    """(verdict, headline, clean text, declined) from the model's answer.

    declined: the answer starts with [[DECLINE]] (the marker is removed from the text). verdict: the first
    token of the answer if it is one of VERDICTS, else None (always None for a declined answer).
    headline: the first sentence after the verdict (the first sentence of the text if there is no verdict).
    """
    text = "" if text is None else str(text).strip()
    declined = text.startswith(DECLINE_MARKER)
    if declined:
        text = text[len(DECLINE_MARKER):].strip()
    verdict, rest = None, text
    if not declined:
        body = text.lstrip(VERDICT_STRIP)
        m = VERDICT_RE.match(body)
        if m:
            verdict, rest = m.group(1), body[m.end():]
    rest = rest.lstrip(" \t\r\n:;,.-–—*_#>)")
    headline = SENTENCE_END_RE.split(rest, 1)[0].strip() if rest else ""
    return verdict, trunc(headline, MAX_HEADLINE), text, declined


def guardrail_intervened(guardrail):
    """True if the guardrail blocked something. Anonymized sensitive data alone is not a refusal."""
    if isinstance(guardrail, dict):
        return str(guardrail.get("action", "")).upper() in ("INTERVENED", "GUARDRAIL_INTERVENED", "BLOCKED")
    if isinstance(guardrail, list):
        return any(isinstance(r, dict) and any(r.get(k) for k in GUARDRAIL_POLICIES) for r in guardrail)
    return False


def _results(tool_results, name):
    """Raw results of one tool as a list (a single dict is accepted too), error results left out."""
    value = _dict(tool_results).get(name)
    items = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
    return [r for r in items if isinstance(r, dict) and not r.get("error")]


def collect_evidence(tool_results):
    """{evidence_id: evidence row} from every tool result that carries an "evidence" list."""
    out = {}
    for results in _dict(tool_results).values():
        for r in results if isinstance(results, list) else [results]:
            for row in _list(_dict(r).get("evidence")):
                if isinstance(row, dict) and isinstance(row.get("evidence_id"), str) and row["evidence_id"]:
                    out.setdefault(row["evidence_id"], row)
    return out


def build_citations(text, evidence):
    """(text with [evidence_id] markers renumbered [1], [2]... in order of appearance, citations list).

    Only markers whose id is an evidence entry of this job's tool results are cited; any other bracket
    is left alone.
    """
    order = []

    def renumber(m):
        eid = m.group(1).strip()
        if eid not in evidence:
            return m.group(0)
        if eid not in order:
            order.append(eid)
        return "[%d]" % (order.index(eid) + 1)

    new_text = EVIDENCE_REF_RE.sub(renumber, text)
    citations = []
    for n, eid in enumerate(order, 1):
        row = evidence[eid]
        citations.append({
            "n": n,
            "evidence_id": eid,
            "excerpt": trunc(row.get("excerpt"), MAX_EXCERPT),
            "publisher": row.get("publisher"),
            "date": row.get("date"),
            "doc_type": row.get("doc_type") or "research",
            "trust": row.get("trust"),
            "url": row.get("source_url") or row.get("url"),
        })
    return new_text, citations


# ----------------------------------------------------------------------------- data (from tool results only)

def empty_data():
    return {"risk_share": {}, "shields": [], "cushion": [], "betas": [], "twin_series": [],
            "stock_bond_series": [], "scenario": None}


def _extend(target, rows, key):
    """Append rows not already in the list (same `key` value) so repeated tool calls do not duplicate."""
    seen = {r.get(key) for r in target}
    for row in rows:
        if row.get(key) not in seen:
            seen.add(row.get(key))
            target.append(row)


def build_data(tool_results):
    """The contract's `data` object, merged deterministically from the raw tool results.

    Nothing here reads the model's text. Fields no tool filled keep their empty value.
    """
    data = empty_data()
    for r in _results(tool_results, "get_portfolio_facts"):
        risk = _dict(r.get("risk_share"))
        data["risk_share"].update({k: risk[k] for k in ("rates", "stocks", "oil") if k in risk})
        _extend(data["shields"], [dict(s) for s in _list(r.get("shields")) if isinstance(s, dict)], "item")
        _extend(data["cushion"], [
            {"asset": c.get("candidate"), "avg_return_pct": c.get("avg_pct_worst"),
             "hit_weeks": c.get("weeks_up"), "n_weeks": c.get("weeks")}
            for c in _list(r.get("cushion_top")) if isinstance(c, dict)], "asset")
        _extend(data["betas"], [
            {"subject": b.get("ticker"), "beta": _dict(b.get("oil")).get("beta"),
             "lo": _dict(b.get("oil")).get("lo"), "hi": _dict(b.get("oil")).get("hi"),
             "p": None, "n_weeks": None}
            for b in _list(r.get("betas")) if isinstance(b, dict)], "subject")
        twin = _dict(r.get("twin_series"))
        months, own, other = _list(twin.get("months")), _list(twin.get("persona")), _list(twin.get("twin"))
        rows = []
        for i, month in enumerate(months):
            rows.append({"week": month, "own": None, "twin": None,
                         "own_dd_pct": own[i] if i < len(own) else None,
                         "twin_dd_pct": other[i] if i < len(other) else None})
        _extend(data["twin_series"], rows, "week")
        sb = _dict(r.get("stock_bond"))
        sb_rows = []
        for pair, entry in _dict(sb.get("by_cpi_regime")).items():
            for measure in ("cpi_ge_3", "cpi_lt_3"):
                if isinstance(entry.get(measure), dict):
                    sb_rows.append({"pair": pair, "measure": measure, "week": None,
                                    "correlation": entry[measure].get("corr"),
                                    "n_weeks": entry[measure].get("n_weeks")})
        roll = _dict(sb.get("rolling_52w_monthly"))
        for pair, values in roll.items():
            if pair == "months" or not isinstance(values, list):
                continue
            for month, corr in zip(_list(roll.get("months")), values):
                if corr is not None:
                    sb_rows.append({"pair": pair, "measure": "rolling_52w", "week": month,
                                    "correlation": corr, "n_weeks": 52})
        seen = {(x["pair"], x["measure"], x["week"]) for x in data["stock_bond_series"]}
        for row in sb_rows:
            k = (row["pair"], row["measure"], row["week"])
            if k not in seen:
                seen.add(k)
                data["stock_bond_series"].append(row)
    for r in _results(tool_results, "test_shield"):
        row = _dict(r.get("worst_weeks"))
        if row:
            shield = {"persona": r.get("persona"), "item": r.get("ticker")}
            shield.update({k: row.get(k) for k in ("label", "avg_pct_worst", "weeks_up", "weeks", "binom_p")})
            data["shields"] = [s for s in data["shields"] if s.get("item") != shield["item"]] + [shield]
    for r in _results(tool_results, "get_portfolio_exposure"):
        pb = _dict(r.get("portfolio_beta"))
        if pb.get("beta") is not None:
            _extend(data["betas"], [{"subject": r.get("persona"), "beta": pb.get("beta"), "lo": pb.get("lo"),
                                     "hi": pb.get("hi"), "p": pb.get("p"), "n_weeks": pb.get("n_weeks")}],
                    "subject")
    for r in _results(tool_results, "run_scenario"):  # the last scenario wins
        if r.get("shock_type") == "rates":
            total = _dict(r.get("total"))
            data["scenario"] = {"subject": r.get("persona"), "subject_type": "persona", "shock_type": "rates",
                                "shock_bp": r.get("rates_shock_bp"), "impact_pct": total.get("impact_pct"),
                                "lo_pct": total.get("lo_pct"), "hi_pct": total.get("hi_pct")}
        else:
            rows = [s for s in _list(r.get("scenario")) if isinstance(s, dict)]
            if rows:
                data["scenario"] = {k: rows[0].get(k) for k in
                                    ("subject", "subject_type", "shock_pct", "impact_pct", "lo_pct", "hi_pct")}
    return data


def _num(value):
    """A finite number (int, float or Decimal) or None; booleans are not numbers."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    value = float(value)
    return value if value == value and abs(value) != float("inf") else None


def _fmt(value, digits=2, signed=False):
    n = _num(value)
    if n is None:
        return None
    return (("%+." if signed else "%.") + str(digits) + "f") % n


def _pick(label, value, suffix="", digits=2, signed=False):
    """'label value' for a number, 'label value' for a non-empty string, else None."""
    text = _fmt(value, digits, signed)
    if text is None and isinstance(value, str) and value:
        text = value
    return "%s %s%s" % (label, text, suffix if _num(value) is not None else "") if text is not None else None


def summarize_result(name, result):
    """Up to 3 key numbers of one raw tool result, as a short string ('' when there is nothing to show)."""
    if isinstance(result, list):
        if result and isinstance(result[0], dict) and result[0].get("error"):
            return trunc("error: %s" % result[0]["error"], MAX_SUMMARY)
        return "%d passages" % len(result)
    if not isinstance(result, dict):
        return ""
    if result.get("error"):
        return trunc("error: %s" % result["error"], MAX_SUMMARY)
    risk, prot = _dict(result.get("risk_share")), _dict(result.get("protection"))
    crash, facts = _dict(result.get("crash_profile")), _dict(result.get("facts"))
    worst, scen_total = _dict(result.get("worst_weeks")), _dict(result.get("total"))
    scen = next((s for s in _list(result.get("scenario")) if isinstance(s, dict)), {})
    conf, val = _dict(result.get("confidence")), _dict(result.get("validation"))
    sens, beta = _dict(result.get("sensitivity")), _dict(result.get("portfolio_beta"))
    comp = _dict(result.get("comparison"))
    if name == "get_portfolio_facts":
        cands = [_pick("crash_type", crash.get("crash_type")), _pick("rates r2", risk.get("rates"), digits=3),
                 _pick("bonds avg", prot.get("avg_bond_return_pct"), "%", signed=True),
                 _pick("stocks r2", risk.get("stocks"), digits=3), _pick("oil r2", risk.get("oil"), digits=3),
                 _pick("max drawdown", facts.get("max_drawdown_pct"), "%", signed=True)]
    elif name == "test_shield":
        cands = [_pick("%s" % result.get("ticker"), worst.get("label")),
                 _pick("avg worst", worst.get("avg_pct_worst"), "%", signed=True),
                 _pick("p", worst.get("binom_p"), digits=3)]
    elif name == "run_scenario" and result.get("shock_type") == "rates":
        cands = [_pick("rates bp", result.get("rates_shock_bp"), digits=0, signed=True),
                 _pick("total", scen_total.get("impact_pct"), "%", signed=True),
                 _pick("per $100k", scen_total.get("per_100k"), digits=0, signed=True)]
    elif name == "run_scenario":
        cands = [_pick("oil %", result.get("oil_shock_pct"), digits=0, signed=True),
                 _pick("impact", scen.get("impact_pct"), "%", signed=True),
                 _pick("lo", scen.get("lo_pct"), "%", signed=True), _pick("hi", scen.get("hi_pct"), "%", signed=True)]
    elif name == "get_portfolio_exposure":
        cands = [_pick("portfolio beta", beta.get("beta")), _pick("lo", beta.get("lo")), _pick("hi", beta.get("hi"))]
    elif name == "get_asset_sensitivity":
        cands = [_pick("%s beta" % result.get("ticker"), sens.get("beta_simple")),
                 _pick("lo", sens.get("lo_simple")), _pick("hi", sens.get("hi_simple"))]
    elif name == "explain_channel":
        cands = [_pick("%s label" % result.get("ticker"), conf.get("label")),
                 _pick("channel", conf.get("channel"))]
    elif name == "get_validation":
        cands = [_pick("label", val.get("label")), _pick("ex-2022 beta", val.get("beta_ex2022")),
                 _pick("oos hit", val.get("oos_hit_rate"))]
    elif name == "compare_alternative":
        cands = [_pick("30% oil before", comp.get("impact30_before_pct"), "%", signed=True),
                 _pick("after", comp.get("impact30_after_pct"), "%", signed=True)]
    else:
        return ""
    return trunc("; ".join([c for c in cands if c][:3]), MAX_SUMMARY)


def build_trace(steps, tool_results):
    """Trace steps capped and truncated. A blank or 'ok' output_summary is rebuilt from the matching tool result
    (the n-th step of a tool pairs with the n-th result of that tool)."""
    seen = {}
    trace = []
    for step in _list(steps)[:MAX_TOOL_CALLS]:
        if not isinstance(step, dict):
            continue
        step = dict(step)
        name = step.get("tool")
        n = seen.get(name, 0)
        seen[name] = n + 1
        summary = step.get("output_summary")
        if summary is None or str(summary).strip().lower() in ("", "ok"):
            results = _dict(tool_results).get(name)
            results = results if isinstance(results, list) else [results] if results is not None else []
            if n < len(results):
                summary = summarize_result(name, results[n]) or summary
        step["output_summary"] = trunc(summary, MAX_SUMMARY)
        step["input_summary"] = trunc(step.get("input_summary"), MAX_SUMMARY)
        trace.append(step)
    return trace


def build_result(agent_response):
    """Contract fields (answer, trace, data, citations) plus the legacy toolCalls/claims from one agent response."""
    raw = agent_response.get("answer_text", agent_response.get("answer"))
    raw = "" if raw is None else raw if isinstance(raw, str) else json.dumps(raw, default=_json_default)
    verdict, headline, text, declined = parse_answer(trunc(raw, MAX_ANSWER))
    tool_results = _dict(agent_response.get("tool_results"))
    text, citations = build_citations(text, collect_evidence(tool_results))
    trace = build_trace(agent_response.get("trace"), tool_results)
    refusal = declined or guardrail_intervened(agent_response.get("guardrail"))
    return {
        "answer": {"verdict": verdict, "headline": headline, "text": text, "refusal": refusal, "caveat": CAVEAT},
        "trace": trace,
        "data": build_data(tool_results),
        "citations": citations[:MAX_CITATIONS],
        "toolCalls": _list(agent_response.get("toolCalls"))[:MAX_TOOL_CALLS],
        "claims": _list(agent_response.get("claims")),
    }


# ----------------------------------------------------------------------------- cache

def cache_key(persona, experiment_id, level):
    return "%s%s#%s#%s" % (CACHE_PREFIX, persona, experiment_id, level)


def find_cached(key, job_id):
    """The finished job stored under the cache key, or None. A refusal is never served from the cache."""
    entry = _table().get_item(Key={"jobId": key}).get("Item")
    source_id = _dict(entry).get("sourceJobId")
    if not source_id or source_id == job_id:
        return None
    source = _table().get_item(Key={"jobId": source_id}).get("Item")
    if not source or source.get("status") != "DONE":
        return None
    answer = source.get("answer")
    if not isinstance(answer, dict) or answer.get("refusal"):
        return None
    return source


def store_cached(key, job_id, expires_at):
    """Point the cache key at this job. Failures are logged, never fatal."""
    try:
        _table().update_item(
            Key={"jobId": key},
            UpdateExpression="SET sourceJobId = :j, expiresAt = :e",
            ExpressionAttributeValues={":j": job_id, ":e": expires_at},
        )
    except Exception as e:
        print(json.dumps({"jobId": job_id, "status": "CACHE_WRITE_FAILED", "error": trunc(e, 200)}))


# ----------------------------------------------------------------------------- job processing

def process(job_id, level=None, experiment_id=None):
    """Process one job. Returns True if handled, raises on throttling.

    level and experiment_id come from the SQS message; the job row has the same values as fallback.
    """
    started = time.time()
    item = _table().get_item(Key={"jobId": job_id}).get("Item")
    if not item:
        print(json.dumps({"jobId": job_id, "status": "MISSING", "durationMs": 0}))
        return
    level = level or item.get("level")
    experiment_id = experiment_id or item.get("experimentId")
    now = int(time.time())
    try:
        _table().update_item(
            Key={"jobId": job_id},
            UpdateExpression="SET #s = :running, startedAtEpoch = :now",
            ConditionExpression="#s = :pending OR (#s = :running AND startedAtEpoch < :stale)",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":running": "RUNNING", ":pending": "PENDING",
                                       ":now": now, ":stale": now - STALE_RUNNING_SECONDS},
        )
    except ClientError as e:
        if _error_code(e) == "ConditionalCheckFailedException":
            _log(job_id, "SKIPPED", started)
            return
        raise

    try:
        if not item.get("stages"):  # a job row written before submit recorded the queued stage
            _add_stages(job_id, ["queued"])
        key = cache_key(item["persona"], experiment_id, level) if experiment_id else None
        cached = find_cached(key, job_id) if key else None
        if cached:
            fields = {k: cached[k] for k in ("answer", "trace", "data", "citations", "toolCalls", "claims")
                      if k in cached}
            _set_status(job_id, "DONE", stages=["done"], cachedFrom=cached["jobId"],
                        finishedAt=datetime.now(timezone.utc).isoformat(),
                        durationMs=int((time.time() - started) * 1000), **fields)
            _log(job_id, "DONE_CACHED", started)
            return

        _add_stages(job_id, ["agent_started"])
        resp = _agent().invoke_agent_runtime(
            agentRuntimeArn=os.environ["AGENT_RUNTIME_ARN"],
            runtimeSessionId=session_id_for(item.get("agentSessionId") or item["sessionId"]),
            payload=json.dumps(
                {"persona": item["persona"], "question": item["question"], "level": level,
                 "experiment_id": experiment_id}
            ),
        )
        data = read_body(resp)
        result = build_result(data)
        trace_key = "traces/%s.json" % job_id
        _s3().put_object(
            Bucket=os.environ["BUCKET"],
            Key=trace_key,
            Body=json.dumps({"jobId": job_id, "response": data}, default=_json_default).encode("utf-8"),
            ContentType="application/json",
        )
        duration = int((time.time() - started) * 1000)
        extra = {}
        if data.get("guardrail") is not None:
            extra["guardrail"] = data["guardrail"]
        # The agent returns one JSON body at the end of the run, so the tool and guardrail stages are
        # written together once it arrives (one tool:<name> stage per trace step).
        stages = ["tool:%s" % step.get("tool") for step in result["trace"]] + ["guardrail", "done"]
        _set_status(
            job_id,
            "DONE",
            stages=stages,
            traceKey=trace_key,
            finishedAt=datetime.now(timezone.utc).isoformat(),
            durationMs=duration,
            **result,
            **extra,
        )
        if key and not result["answer"]["refusal"]:
            store_cached(key, job_id, int(item.get("expiresAt") or now + 86400))
        _log(job_id, "DONE", started)
    except Exception as e:
        if _error_code(e) in THROTTLE_CODES:
            # release the job so the SQS redelivery can claim it again
            try:
                _set_status(job_id, "PENDING")
            finally:
                _log(job_id, "THROTTLED", started)
            raise
        _set_status(
            job_id,
            "FAILED",
            stages=["failed"],
            error=trunc("%s: %s" % (type(e).__name__, e), 500),
            finishedAt=datetime.now(timezone.utc).isoformat(),
            durationMs=int((time.time() - started) * 1000),
        )
        _log(job_id, "FAILED", started)


def lambda_handler(event, context):
    failures = []
    for record in event.get("Records", []):
        try:
            message = json.loads(record["body"])
            process(message["jobId"], message.get("level"), message.get("experiment_id"))
        except Exception as e:
            if _error_code(e) in THROTTLE_CODES:
                failures.append({"itemIdentifier": record["messageId"]})
            else:
                print(json.dumps({"status": "ERROR", "error": trunc(e, 200)}))
    return {"batchItemFailures": failures}
