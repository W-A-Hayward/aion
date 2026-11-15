import json
import os
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

MAX_TOOL_CALLS = 20
MAX_CITATIONS = 10
MAX_ANSWER = 100_000
MAX_TOOL_RESPONSE = 1000
MAX_PARAM_VALUE = 500
MAX_EXCERPT = 500
THROTTLE_CODES = {
    "ThrottlingException",
    "throttlingException",
    "TooManyRequestsException",
    "ProvisionedThroughputExceededException",
    "RequestLimitExceeded",
    "ServiceUnavailableException",
}

_clients = {}


def _table():
    if "table" not in _clients:
        _clients["table"] = boto3.resource("dynamodb").Table(os.environ["JOBS_TABLE"])
    return _clients["table"]


def _agent():
    if "agent" not in _clients:
        _clients["agent"] = boto3.client("bedrock-agent-runtime")
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


def parse_stream(stream):
    """Consume an invoke_agent event stream.

    Returns (answer, trace_events, tool_calls, citations, guardrails).
    """
    answer = []
    traces = []
    tool_calls = []
    citations = []
    guardrails = []
    seen = set()

    def add_citation(ref):
        uri = ((ref.get("location") or {}).get("s3Location") or {}).get("uri")
        if uri is None:
            loc = ref.get("location") or {}
            uri = (loc.get("webLocation") or {}).get("url") or ""
        excerpt = (ref.get("content") or {}).get("text", "")
        key = (uri, excerpt[:100])
        if key in seen:
            return
        seen.add(key)
        citations.append({"source": uri, "excerpt": trunc(excerpt, MAX_EXCERPT)})

    for event in stream:
        if "chunk" in event:
            chunk = event["chunk"]
            data = chunk.get("bytes", b"")
            answer.append(data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data))
            for c in (chunk.get("attribution") or {}).get("citations", []):
                for ref in c.get("retrievedReferences", []):
                    add_citation(ref)
        elif "trace" in event:
            tr = event["trace"].get("trace", {})
            traces.append(tr)
            orch = tr.get("orchestrationTrace") or {}
            inv = (orch.get("invocationInput") or {}).get("actionGroupInvocationInput")
            if inv:
                params = {
                    p.get("name", ""): trunc(p.get("value"), MAX_PARAM_VALUE)
                    for p in inv.get("parameters", [])
                }
                if not params and inv.get("requestBody"):
                    params = {"requestBody": trunc(json.dumps(inv["requestBody"], default=str), MAX_PARAM_VALUE)}
                tool_calls.append(
                    {
                        "function": inv.get("function") or inv.get("apiPath") or "",
                        "actionGroup": inv.get("actionGroupName", ""),
                        "parameters": params,
                        "response": None,
                    }
                )
            obs = orch.get("observation") or {}
            out = obs.get("actionGroupInvocationOutput")
            if out is not None:
                for call in reversed(tool_calls):
                    if call["response"] is None:
                        call["response"] = trunc(out.get("text", ""), MAX_TOOL_RESPONSE)
                        break
            kb = obs.get("knowledgeBaseLookupOutput")
            if kb:
                for ref in kb.get("retrievedReferences", []):
                    add_citation(ref)
            g = tr.get("guardrailTrace")
            if g and g.get("action") == "INTERVENED":
                guardrails.append(g)
    return "".join(answer), traces, tool_calls, citations, guardrails


def _log(job_id, status, started):
    print(json.dumps({"jobId": job_id, "status": status, "durationMs": int((time.time() - started) * 1000)}))


def _set_status(job_id, status, **fields):
    names = {"#s": "status"}
    values = {":s": status}
    sets = ["#s = :s"]
    for i, (k, v) in enumerate(fields.items()):
        names["#f%d" % i] = k
        values[":v%d" % i] = v
        sets.append("#f%d = :v%d" % (i, i))
    _table().update_item(
        Key={"jobId": job_id},
        UpdateExpression="SET " + ", ".join(sets),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def process(job_id):
    """Process one job. Returns True if handled, raises on throttling."""
    started = time.time()
    item = _table().get_item(Key={"jobId": job_id}).get("Item")
    if not item:
        print(json.dumps({"jobId": job_id, "status": "MISSING", "durationMs": 0}))
        return
    try:
        _table().update_item(
            Key={"jobId": job_id},
            UpdateExpression="SET #s = :running",
            ConditionExpression="#s = :pending",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":running": "RUNNING", ":pending": "PENDING"},
        )
    except ClientError as e:
        if _error_code(e) == "ConditionalCheckFailedException":
            _log(job_id, "SKIPPED", started)
            return
        raise

    try:
        resp = _agent().invoke_agent(
            agentId=os.environ["AGENT_ID"],
            agentAliasId=os.environ["AGENT_ALIAS_ID"],
            sessionId=item["sessionId"],
            inputText=item["question"],
            enableTrace=True,
            sessionState={"promptSessionAttributes": {"persona": item["persona"], "level": item["level"]}},
        )
        answer, traces, tool_calls, citations, guardrails = parse_stream(resp["completion"])
        trace_key = "traces/%s.json" % job_id
        _s3().put_object(
            Bucket=os.environ["BUCKET"],
            Key=trace_key,
            Body=json.dumps(
                {
                    "jobId": job_id,
                    "answer": answer,
                    "toolCalls": tool_calls,
                    "citations": citations,
                    "guardrails": guardrails,
                    "trace": traces,
                },
                default=str,
            ).encode("utf-8"),
            ContentType="application/json",
        )
        duration = int((time.time() - started) * 1000)
        _set_status(
            job_id,
            "DONE",
            answer=trunc(answer, MAX_ANSWER),
            toolCalls=tool_calls[:MAX_TOOL_CALLS],
            citations=citations[:MAX_CITATIONS],
            traceKey=trace_key,
            finishedAt=datetime.now(timezone.utc).isoformat(),
            durationMs=duration,
        )
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
            error=trunc("%s: %s" % (type(e).__name__, e), 500),
            finishedAt=datetime.now(timezone.utc).isoformat(),
            durationMs=int((time.time() - started) * 1000),
        )
        _log(job_id, "FAILED", started)


def lambda_handler(event, context):
    failures = []
    for record in event.get("Records", []):
        try:
            job_id = json.loads(record["body"])["jobId"]
            process(job_id)
        except Exception as e:
            if _error_code(e) in THROTTLE_CODES:
                failures.append({"itemIdentifier": record["messageId"]})
            else:
                print(json.dumps({"status": "ERROR", "error": trunc(e, 200)}))
    return {"batchItemFailures": failures}
