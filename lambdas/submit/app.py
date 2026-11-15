import base64
import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

PERSONAS = ("robert", "amira", "mateo")
LEVELS = ("beginner", "expert")
SESSION_RE = re.compile(r"[A-Za-z0-9-]{1,100}")
# Browser-held secret that owns the jobs it submits (see docs/infrastructure.md, "Access control").
TOKEN_HEADER = "x-cascade-session"
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{32,128}")
TTL_SECONDS = 86400
RATE_WINDOW_SECONDS = 60

_clients = {}


def _table():
    if "table" not in _clients:
        _clients["table"] = boto3.resource("dynamodb").Table(os.environ["JOBS_TABLE"])
    return _clients["table"]


def _sqs():
    if "sqs" not in _clients:
        _clients["sqs"] = boto3.client("sqs")
    return _clients["sqs"]


def _cors():
    origin = os.environ.get("ALLOWED_ORIGIN")
    return {"access-control-allow-origin": origin, "vary": "Origin"} if origin else {}


def _resp(code, body, headers=None):
    return {
        "statusCode": code,
        "headers": {"content-type": "application/json", **_cors(), **(headers or {})},
        "body": json.dumps(body),
    }


def _header(event, name):
    for k, v in ((event or {}).get("headers") or {}).items():
        if isinstance(k, str) and k.lower() == name:
            return v
    return None


def owner_of(event):
    """Return the job owner hash, or None.

    A signed-in user (API Gateway JWT authorizer, e.g. Cognito) owns jobs by their `sub`.
    Otherwise the browser's random session token in the x-cascade-session header does.
    Only a SHA-256 of the identity is stored.
    """
    claims = ((((event or {}).get("requestContext") or {}).get("authorizer") or {}).get("jwt") or {}).get("claims") or {}
    sub = claims.get("sub")
    if isinstance(sub, str) and sub:
        return hashlib.sha256(("user:" + sub).encode()).hexdigest()
    token = _header(event, TOKEN_HEADER)
    if isinstance(token, str) and TOKEN_RE.fullmatch(token):
        return hashlib.sha256(("session:" + token).encode()).hexdigest()
    return None


def _source_ip(event):
    ip = (((event or {}).get("requestContext") or {}).get("http") or {}).get("sourceIp")
    return ip if isinstance(ip, str) and ip else "unknown"


def _limit(name, default):
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


def take_rate_token(kind, key, limit, now=None):
    """Count one request in a fixed one-minute window. False if the window is already full.

    Counters live in the jobs table under "rate#..." keys, which never parse as a job UUID,
    and expire through the table's TTL.
    """
    now = int(now if now is not None else time.time())
    window = now // RATE_WINDOW_SECONDS
    counter = "rate#%s#%s#%d" % (kind, key[:32], window)
    try:
        _table().update_item(
            Key={"jobId": counter},
            UpdateExpression="ADD #n :one SET expiresAt = :exp",
            ConditionExpression="attribute_not_exists(#n) OR #n < :limit",
            ExpressionAttributeNames={"#n": "n"},
            ExpressionAttributeValues={":one": 1, ":limit": limit, ":exp": now + 2 * RATE_WINDOW_SECONDS},
        )
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def _parse_body(event):
    raw = event.get("body")
    if raw is None:
        raise ValueError("body is required")
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        raise ValueError("body must be valid JSON")
    if not isinstance(data, dict):
        raise ValueError("body must be a JSON object")
    return data


def validate(data):
    """Return (clean dict, None) or (None, error message)."""
    q = data.get("question")
    if not isinstance(q, str) or not q.strip() or len(q) > 1000:
        return None, "question must be a string of 1-1000 characters"
    persona = data.get("persona")
    if persona not in PERSONAS:
        return None, "persona must be one of: " + ", ".join(PERSONAS)
    level = data.get("level")
    if level not in LEVELS:
        return None, "level must be one of: " + ", ".join(LEVELS)
    sid = data.get("sessionId")
    if sid is not None and not (isinstance(sid, str) and SESSION_RE.fullmatch(sid)):
        return None, "sessionId must match [A-Za-z0-9-]{1,100}"
    return {"question": q, "persona": persona, "level": level, "sessionId": sid}, None


def lambda_handler(event, context):
    event = event or {}
    if (((event.get("requestContext") or {}).get("http") or {}).get("method")) == "OPTIONS":
        return _resp(204, {})
    owner = owner_of(event)
    if owner is None:
        return _resp(401, {"error": "sign in, or send a random 32-128 character %s header" % TOKEN_HEADER})
    try:
        data = _parse_body(event)
    except ValueError as e:
        return _resp(400, {"error": str(e)})
    clean, err = validate(data)
    if err:
        return _resp(400, {"error": err})

    ip_hash = hashlib.sha256(_source_ip(event).encode()).hexdigest()
    if not take_rate_token("owner", owner, _limit("RATE_PER_OWNER_PER_MIN", 5)) or \
            not take_rate_token("ip", ip_hash, _limit("RATE_PER_IP_PER_MIN", 30)):
        return _resp(429, {"error": "too many questions; wait a minute and try again"},
                     {"retry-after": str(RATE_WINDOW_SECONDS)})

    job_id = str(uuid.uuid4())
    session_id = clean["sessionId"] or str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    item = {
        "jobId": job_id,
        "status": "PENDING",
        "question": clean["question"],
        "persona": clean["persona"],
        "level": clean["level"],
        "sessionId": session_id,
        # Agent session scoped to the owner, so a guessed sessionId cannot join someone else's.
        "agentSessionId": "%s-%s" % (owner[:16], session_id),
        "ownerHash": owner,
        "createdAt": now.isoformat(),
        "expiresAt": int(time.time()) + TTL_SECONDS,
    }
    _table().put_item(Item=item)
    try:
        _sqs().send_message(QueueUrl=os.environ["QUEUE_URL"], MessageBody=json.dumps({"jobId": job_id}))
    except Exception as e:
        # The job row exists but nothing will process it: mark it failed instead of leaving PENDING.
        _table().update_item(
            Key={"jobId": job_id},
            UpdateExpression="SET #s = :failed, #e = :err",
            ExpressionAttributeNames={"#s": "status", "#e": "error"},
            ExpressionAttributeValues={":failed": "FAILED", ":err": "could not queue the job: %s" % type(e).__name__},
        )
        print(json.dumps({"jobId": job_id, "status": "ENQUEUE_FAILED", "error": type(e).__name__}))
        return _resp(503, {"error": "the question could not be queued; try again"})
    print(json.dumps({"jobId": job_id, "status": "PENDING", "durationMs": 0}))
    return _resp(202, {"jobId": job_id, "sessionId": session_id})
