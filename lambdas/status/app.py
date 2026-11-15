import json
import os
import uuid
from decimal import Decimal

import boto3

_clients = {}

FIELDS = ("status", "answer", "toolCalls", "citations", "error", "durationMs")


def _table():
    if "table" not in _clients:
        _clients["table"] = boto3.resource("dynamodb").Table(os.environ["JOBS_TABLE"])
    return _clients["table"]


def _default(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    raise TypeError(type(o).__name__)


def _resp(code, body):
    return {
        "statusCode": code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, default=_default),
    }


def _valid_uuid(value):
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value.lower()
    except ValueError:
        return False


def lambda_handler(event, context):
    job_id = ((event or {}).get("pathParameters") or {}).get("id")
    if not _valid_uuid(job_id):
        return _resp(400, {"error": "id must be a UUID"})
    job_id = job_id.lower()
    item = _table().get_item(Key={"jobId": job_id}).get("Item")
    if not item:
        return _resp(404, {"error": "job not found"})
    body = {"jobId": item["jobId"]}
    for f in FIELDS:
        if f in item:
            body[f] = item[f]
    return _resp(200, body)
