import hashlib
import hmac
import json
import os
import re
import uuid
from decimal import Decimal

import boto3

_clients = {}

# Fields outside the contract that eval/ and the smoke test still read. answer and citations follow the contract.
LEGACY_FIELDS = ("toolCalls", "claims", "error", "durationMs")
LEGACY_STAGE = {"PENDING": "queued", "RUNNING": "agent_started", "DONE": "done", "FAILED": "failed"}
EMPTY_DATA = {"risk_share": {}, "shields": [], "cushion": [], "betas": [], "twin_series": [],
              "stock_bond_series": [], "scenario": None}
TOKEN_HEADER = "x-cascade-session"
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{32,128}")


def _table():
    if "table" not in _clients:
        _clients["table"] = boto3.resource("dynamodb").Table(os.environ["JOBS_TABLE"])
    return _clients["table"]


def _default(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    raise TypeError(type(o).__name__)


def _cors():
    origin = os.environ.get("ALLOWED_ORIGIN")
    return {"access-control-allow-origin": origin, "vary": "Origin"} if origin else {}


def _resp(code, body):
    return {
        "statusCode": code,
        "headers": {"content-type": "application/json", "cache-control": "no-store", **_cors()},
        "body": json.dumps(body, default=_default),
    }


def _valid_uuid(value):
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value.lower()
    except ValueError:
        return False


def _header(event, name):
    for k, v in ((event or {}).get("headers") or {}).items():
        if isinstance(k, str) and k.lower() == name:
            return v
    return None


def owner_of(event):
    """Same identity rule as lambdas/submit/app.py owner_of (keep the two in sync)."""
    claims = ((((event or {}).get("requestContext") or {}).get("authorizer") or {}).get("jwt") or {}).get("claims") or {}
    sub = claims.get("sub")
    if isinstance(sub, str) and sub:
        return hashlib.sha256(("user:" + sub).encode()).hexdigest()
    token = _header(event, TOKEN_HEADER)
    if isinstance(token, str) and TOKEN_RE.fullmatch(token):
        return hashlib.sha256(("session:" + token).encode()).hexdigest()
    return None


def lambda_handler(event, context):
    event = event or {}
    if (((event.get("requestContext") or {}).get("http") or {}).get("method")) == "OPTIONS":
        return _resp(204, {})
    owner = owner_of(event)
    if owner is None:
        return _resp(401, {"error": "sign in, or send the %s header used to submit the job" % TOKEN_HEADER})
    job_id = (event.get("pathParameters") or {}).get("id")
    if not _valid_uuid(job_id):
        return _resp(400, {"error": "id must be a UUID"})
    job_id = job_id.lower()
    item = _table().get_item(Key={"jobId": job_id}).get("Item")
    # A job owned by someone else (or by no one) is reported exactly like a missing job.
    if not item or not isinstance(item.get("ownerHash"), str) or not hmac.compare_digest(item["ownerHash"], owner):
        return _resp(404, {"error": "job not found"})
    return _resp(200, contract_body(item))


def contract_body(item):
    """The GET /jobs/{id} object of docs/api_contract.md, plus the legacy fields clients already read."""
    stages = [s for s in (item.get("stages") or []) if isinstance(s, dict)]
    status = item.get("status")
    stage = stages[-1].get("stage") if stages else LEGACY_STAGE.get(status, "queued")
    answer = item.get("answer")
    if isinstance(answer, str):  # a job finished before the contract object existed
        answer = {"verdict": None, "headline": "", "text": answer, "refusal": False, "caveat": None}
    data = dict(EMPTY_DATA)
    if isinstance(item.get("data"), dict):
        data.update(item["data"])
    body = {
        "job_id": item["jobId"],
        "stage": stage,
        "stages": stages,
        "answer": answer if isinstance(answer, dict) else None,
        "trace": item.get("trace") or [],
        "data": data,
        "citations": item.get("citations") or [],
        "jobId": item["jobId"],
        "status": status,
    }
    for f in LEGACY_FIELDS:
        if f in item:
            body[f] = item[f]
    return body
