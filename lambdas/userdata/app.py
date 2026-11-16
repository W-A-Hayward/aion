"""cascade-userdata: a signed-in user's profile, portfolio and conversations.

HTTP API routes, all behind the Cognito JWT authorizer (the user is the token's `sub`, never a request field):
  GET    /me              -> {username, workspace, chats: [{id, title, updatedAt}]}
  PUT    /me              body {workspace}          -> {ok, updatedAt}
  DELETE /me              -> deletes every item of this user (account deletion)
  GET    /me/chats/{id}   -> the stored conversation
  PUT    /me/chats/{id}   body {conversation}       -> {ok, updatedAt}
  DELETE /me/chats/{id}   -> {ok}

DynamoDB table USERS_TABLE: partition key userId (string), sort key item (string): "profile" or "chat#<id>".
Payloads are stored as JSON strings, so float weights need no Decimal conversion.
"""
import json
import os
import re
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

CHAT_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
MAX_WORKSPACE_BYTES = 50_000
MAX_CHAT_BYTES = 350_000  # DynamoDB items are limited to 400 KB
MAX_CHATS = 200
MAX_TITLE = 120

_clients = {}


def _table():
    if "table" not in _clients:
        _clients["table"] = boto3.resource("dynamodb").Table(os.environ["USERS_TABLE"])
    return _clients["table"]


def _cors():
    origin = os.environ.get("ALLOWED_ORIGIN")
    return {"access-control-allow-origin": origin, "vary": "Origin"} if origin else {}


def _resp(code, body):
    return {
        "statusCode": code,
        "headers": {"content-type": "application/json", "cache-control": "no-store", **_cors()},
        "body": json.dumps(body),
    }


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def claims_of(event):
    return ((((event or {}).get("requestContext") or {}).get("authorizer") or {}).get("jwt") or {}).get("claims") or {}


def _body(event, limit):
    raw = event.get("body")
    if raw is None:
        raise ValueError("body is required")
    if event.get("isBase64Encoded"):
        import base64
        raw = base64.b64decode(raw).decode("utf-8")
    if len(raw.encode("utf-8")) > limit:
        raise OverflowError("body is larger than %d bytes" % limit)
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        raise ValueError("body must be valid JSON")
    if not isinstance(data, dict):
        raise ValueError("body must be a JSON object")
    return data


def _list_chats(user):
    out, start = [], None
    while len(out) < MAX_CHATS:
        kw = {"KeyConditionExpression": Key("userId").eq(user) & Key("item").begins_with("chat#"),
              "ProjectionExpression": "#i, title, updatedAt", "ExpressionAttributeNames": {"#i": "item"}}
        if start:
            kw["ExclusiveStartKey"] = start
        page = _table().query(**kw)
        out += [{"id": r["item"][5:], "title": r.get("title") or "Conversation", "updatedAt": r.get("updatedAt")}
                for r in page.get("Items", [])]
        start = page.get("LastEvaluatedKey")
        if not start:
            break
    return sorted(out, key=lambda c: c.get("updatedAt") or "", reverse=True)[:MAX_CHATS]


def _delete_all(user):
    start, n = None, 0
    while True:
        kw = {"KeyConditionExpression": Key("userId").eq(user), "ProjectionExpression": "#i",
              "ExpressionAttributeNames": {"#i": "item"}}
        if start:
            kw["ExclusiveStartKey"] = start
        page = _table().query(**kw)
        with _table().batch_writer() as batch:
            for r in page.get("Items", []):
                batch.delete_item(Key={"userId": user, "item": r["item"]})
                n += 1
        start = page.get("LastEvaluatedKey")
        if not start:
            return n


def route(event):
    method = (((event.get("requestContext") or {}).get("http") or {}).get("method") or "").upper()
    path = (((event.get("requestContext") or {}).get("http") or {}).get("path") or event.get("rawPath") or "")
    if method == "OPTIONS":
        return _resp(204, {})
    claims = claims_of(event)
    user = claims.get("sub")
    if not isinstance(user, str) or not user:
        return _resp(401, {"error": "sign in first"})
    username = claims.get("cognito:username") or claims.get("username") or ""
    chat_id = (event.get("pathParameters") or {}).get("id")
    is_chat = "/me/chats/" in path

    if is_chat:
        if not isinstance(chat_id, str) or not CHAT_ID_RE.fullmatch(chat_id):
            return _resp(400, {"error": "conversation id must match [A-Za-z0-9_-]{1,64}"})
        key = {"userId": user, "item": "chat#" + chat_id}
        if method == "GET":
            item = _table().get_item(Key=key).get("Item")
            if not item:
                return _resp(404, {"error": "conversation not found"})
            return _resp(200, json.loads(item["data"]))
        if method == "PUT":
            data = _body(event, MAX_CHAT_BYTES)
            chat = data.get("conversation")
            if not isinstance(chat, dict) or not isinstance(chat.get("messages"), list):
                return _resp(400, {"error": "conversation must be an object with a messages list"})
            chat["id"] = chat_id
            now = _now()
            title = chat.get("title") if isinstance(chat.get("title"), str) else "Conversation"
            _table().put_item(Item={**key, "title": title[:MAX_TITLE], "updatedAt": chat.get("updatedAt") or now,
                                    "data": json.dumps(chat)})
            return _resp(200, {"ok": True, "updatedAt": now})
        if method == "DELETE":
            _table().delete_item(Key=key)
            return _resp(200, {"ok": True})
        return _resp(405, {"error": "method not allowed"})

    if method == "GET":
        item = _table().get_item(Key={"userId": user, "item": "profile"}).get("Item")
        return _resp(200, {"username": username, "workspace": json.loads(item["data"]) if item else None,
                           "chats": _list_chats(user)})
    if method == "PUT":
        data = _body(event, MAX_WORKSPACE_BYTES)
        workspace = data.get("workspace")
        if not isinstance(workspace, dict):
            return _resp(400, {"error": "workspace must be an object"})
        now = _now()
        _table().put_item(Item={"userId": user, "item": "profile", "updatedAt": now, "data": json.dumps(workspace)})
        return _resp(200, {"ok": True, "updatedAt": now})
    if method == "DELETE":
        return _resp(200, {"ok": True, "deleted": _delete_all(user)})
    return _resp(405, {"error": "method not allowed"})


def lambda_handler(event, context):
    event = event if isinstance(event, dict) else {}
    try:
        return route(event)
    except OverflowError as e:
        return _resp(413, {"error": str(e)})
    except ValueError as e:
        return _resp(400, {"error": str(e)})
    except Exception as e:  # never leak internals
        print(json.dumps({"status": "ERROR", "error": type(e).__name__}))
        return _resp(500, {"error": "the request could not be completed"})
