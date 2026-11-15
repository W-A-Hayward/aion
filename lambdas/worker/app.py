import json
import os
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
        resp = _agent().invoke_agent_runtime(
            agentRuntimeArn=os.environ["AGENT_RUNTIME_ARN"],
            runtimeSessionId=session_id_for(item.get("agentSessionId") or item["sessionId"]),
            payload=json.dumps(
                {"question": item["question"], "persona": item["persona"], "level": item["level"]}
            ),
        )
        data = read_body(resp)
        answer = data.get("answer")
        answer = "" if answer is None else answer if isinstance(answer, str) else json.dumps(answer, default=_json_default)
        tool_calls = _list(data.get("toolCalls"))
        citations = _list(data.get("citations"))
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
        _set_status(
            job_id,
            "DONE",
            answer=trunc(answer, MAX_ANSWER),
            toolCalls=tool_calls[:MAX_TOOL_CALLS],
            citations=citations[:MAX_CITATIONS],
            traceKey=trace_key,
            finishedAt=datetime.now(timezone.utc).isoformat(),
            durationMs=duration,
            **extra,
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
