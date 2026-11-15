import hashlib
import hmac
import json
import os
import re
import uuid
from decimal import Decimal

import boto3

_clients = {}

FIELDS = ("status", "answer", "toolCalls", "citations", "error", "durationMs")
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
    body = {"jobId": item["jobId"]}
    for f in FIELDS:
        if f in item:
            body[f] = item[f]
    return _resp(200, body)
