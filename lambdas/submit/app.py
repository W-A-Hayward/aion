import base64
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone

import boto3

PERSONAS = ("robert", "amira", "mateo")
LEVELS = ("beginner", "expert")
SESSION_RE = re.compile(r"[A-Za-z0-9-]{1,100}")
TTL_SECONDS = 86400

_clients = {}


def _table():
    if "table" not in _clients:
        _clients["table"] = boto3.resource("dynamodb").Table(os.environ["JOBS_TABLE"])
    return _clients["table"]


def _sqs():
    if "sqs" not in _clients:
        _clients["sqs"] = boto3.client("sqs")
    return _clients["sqs"]


def _resp(code, body):
    return {
        "statusCode": code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }


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
    try:
        data = _parse_body(event or {})
    except ValueError as e:
        return _resp(400, {"error": str(e)})
    clean, err = validate(data)
    if err:
        return _resp(400, {"error": err})

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
        "createdAt": now.isoformat(),
        "expiresAt": int(time.time()) + TTL_SECONDS,
    }
    _table().put_item(Item=item)
    _sqs().send_message(QueueUrl=os.environ["QUEUE_URL"], MessageBody=json.dumps({"jobId": job_id}))
    print(json.dumps({"jobId": job_id, "status": "PENDING", "durationMs": 0}))
    return _resp(202, {"jobId": job_id, "sessionId": session_id})
