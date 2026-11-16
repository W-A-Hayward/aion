import importlib.util
import json
import os

import pytest

_spec = importlib.util.spec_from_file_location("userdata_app", os.path.join(os.path.dirname(__file__), "app.py"))
app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(app)


def _conds(cond):
    """(attribute, operator, value) triples from a boto3 Key condition."""
    e = cond.get_expression()
    if e["operator"] == "AND":
        return _conds(e["values"][0]) + _conds(e["values"][1])
    return [(e["values"][0].name, e["operator"], e["values"][1])]


class FakeTable:
    def __init__(self, page_size=2):
        self.items = {}
        self.page_size = page_size

    def get_item(self, Key):
        item = self.items.get((Key["userId"], Key["item"]))
        return {"Item": dict(item)} if item else {}

    def put_item(self, Item):
        for v in Item.values():
            assert not isinstance(v, float), "DynamoDB items must not hold raw floats"
        self.items[(Item["userId"], Item["item"])] = dict(Item)

    def delete_item(self, Key):
        self.items.pop((Key["userId"], Key["item"]), None)

    def query(self, KeyConditionExpression, ExclusiveStartKey=None, **kw):
        rows = sorted(self.items.values(), key=lambda r: (r["userId"], r["item"]))
        for attr, op, val in _conds(KeyConditionExpression):
            rows = [r for r in rows if (r[attr] == val if op == "=" else r[attr].startswith(val))]
        if ExclusiveStartKey:
            rows = [r for r in rows if r["item"] > ExclusiveStartKey["item"]]
        page = rows[:self.page_size]
        out = {"Items": [dict(r) for r in page]}
        if len(rows) > self.page_size:
            out["LastEvaluatedKey"] = {"userId": page[-1]["userId"], "item": page[-1]["item"]}
        return out

    def batch_writer(self):
        table = self

        class Batch:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def delete_item(self, Key):
                table.delete_item(Key)
        return Batch()


@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(app, "_table", lambda: t)
    return t


def ev(method, path, body=None, sub="user-1", username="robin", chat_id=None):
    event = {"requestContext": {"http": {"method": method, "path": path}}, "rawPath": path}
    if sub is not None:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": {"sub": sub, "cognito:username": username}}}
    if chat_id is not None:
        event["pathParameters"] = {"id": chat_id}
    if body is not None:
        event["body"] = body if isinstance(body, str) else json.dumps(body)
    return event


def call(*a, **k):
    r = app.lambda_handler(ev(*a, **k), None)
    return r["statusCode"], json.loads(r["body"])


WS = {"version": 1, "profile": {"name": "Robin", "experience": "expert"}, "portfolio": "custom", "capital": 25000,
      "custom": {"name": "My mix", "holdings": [{"ticker": "XIU.TO", "weight": 0.6}, {"ticker": "ENB.TO", "weight": 0.4}]}}


def chat(i, title="Q", n=2):
    return {"id": "c%d" % i, "title": title, "updatedAt": "2026-11-16T00:0%d:00Z" % i,
            "messages": [{"role": "user", "text": "hello %d" % k} for k in range(n)]}


def test_requires_a_signed_in_user(table):
    for method, path in (("GET", "/me"), ("PUT", "/me"), ("GET", "/me/chats/c1"), ("DELETE", "/me")):
        code, body = call(method, path, sub=None)
        assert code == 401 and "sign in" in body["error"]
    assert table.items == {}


def test_profile_and_portfolio_round_trip(table):
    code, body = call("GET", "/me")
    assert code == 200 and body == {"username": "robin", "workspace": None, "chats": []}
    assert call("PUT", "/me", {"workspace": WS})[0] == 200
    code, body = call("GET", "/me")
    assert body["workspace"] == WS, "floats survive as JSON"
    assert table.items[("user-1", "profile")]["data"] == json.dumps(WS)


def test_conversations_are_listed_newest_first_across_pages(table):
    for i in range(5):
        assert call("PUT", "/me/chats/c%d" % i, {"conversation": chat(i, "Question %d" % i)}, chat_id="c%d" % i)[0] == 200
    code, body = call("GET", "/me")
    assert [c["id"] for c in body["chats"]] == ["c4", "c3", "c2", "c1", "c0"]
    assert body["chats"][0]["title"] == "Question 4"
    code, got = call("GET", "/me/chats/c2", chat_id="c2")
    assert code == 200 and got["messages"][1]["text"] == "hello 1" and got["id"] == "c2"
    assert call("DELETE", "/me/chats/c2", chat_id="c2")[0] == 200
    assert call("GET", "/me/chats/c2", chat_id="c2")[0] == 404


def test_users_never_see_each_others_data(table):
    call("PUT", "/me", {"workspace": WS})
    call("PUT", "/me/chats/c1", {"conversation": chat(1)}, chat_id="c1")
    code, body = call("GET", "/me", sub="user-2", username="someone")
    assert body == {"username": "someone", "workspace": None, "chats": []}
    assert call("GET", "/me/chats/c1", sub="user-2", chat_id="c1")[0] == 404
    call("DELETE", "/me/chats/c1", sub="user-2", chat_id="c1")
    assert ("user-1", "chat#c1") in table.items, "another user cannot delete it"


@pytest.mark.parametrize("method,path,body,chat_id,code", [
    ("PUT", "/me", "not json", None, 400),
    ("PUT", "/me", {"workspace": "x"}, None, 400),
    ("PUT", "/me", None, None, 400),
    ("PUT", "/me", {"workspace": {"blob": "x" * 60_000}}, None, 413),
    ("PUT", "/me/chats/bad id", {"conversation": chat(1)}, "bad id", 400),
    ("PUT", "/me/chats/c1", {"conversation": {"messages": "nope"}}, "c1", 400),
    ("PUT", "/me/chats/c1", {"conversation": {"messages": [{"text": "x" * 400_000}]}}, "c1", 413),
    ("PATCH", "/me", {"workspace": WS}, None, 405),
])
def test_bad_requests_are_rejected_without_writing(table, method, path, body, chat_id, code):
    assert call(method, path, body, chat_id=chat_id)[0] == code
    assert table.items == {}


def test_delete_account_removes_everything_of_that_user_only(table):
    call("PUT", "/me", {"workspace": WS})
    for i in range(3):
        call("PUT", "/me/chats/c%d" % i, {"conversation": chat(i)}, chat_id="c%d" % i)
    call("PUT", "/me", {"workspace": WS}, sub="user-2")
    code, body = call("DELETE", "/me")
    assert code == 200 and body["deleted"] == 4
    assert list(table.items) == [("user-2", "profile")]


def test_errors_do_not_leak_internals(table, monkeypatch):
    def boom(**k):
        raise RuntimeError("secret table name")
    monkeypatch.setattr(table, "get_item", boom)
    code, body = call("GET", "/me")
    assert code == 500 and "secret" not in json.dumps(body)


def test_preflight_and_cors(table, monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGIN", "https://ripple.example")
    r = app.lambda_handler(ev("OPTIONS", "/me", sub=None), None)
    assert r["statusCode"] == 204 and r["headers"]["access-control-allow-origin"] == "https://ripple.example"
