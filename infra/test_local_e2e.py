"""Local end-to-end run of the real submit, worker, status and research handlers.

A small HTTP server stands in for API Gateway (HTTP API, payload v2). DynamoDB, SQS, S3, Athena and
the AgentCore runtime are in-memory fakes. infra/smoke_test.py then runs against it unchanged, so
this test proves the smoke test and the handler wiring before anything is deployed. No AWS access.
"""
import importlib.util
import io
import json
import os
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from botocore.exceptions import ClientError

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ORIGIN = "https://cascade.example"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


submit = load("lambdas/submit/app.py", "e2e_submit")
status = load("lambdas/status/app.py", "e2e_status")
worker = load("lambdas/worker/app.py", "e2e_worker")
research = load("lambdas/research/app.py", "e2e_research")
smoke = load("infra/smoke_test.py", "e2e_smoke")


class FakeDynamo:
    """Enough of a DynamoDB Table for these handlers: SET/ADD updates and the conditions they use."""

    def __init__(self):
        self.items, self.lock = {}, threading.Lock()

    def put_item(self, Item):
        with self.lock:
            self.items[Item["jobId"]] = dict(Item)

    def get_item(self, Key):
        with self.lock:
            item = self.items.get(Key["jobId"])
            return {"Item": dict(item)} if item else {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames=None, ExpressionAttributeValues=None,
                    ConditionExpression=None):
        names, values = ExpressionAttributeNames or {}, ExpressionAttributeValues or {}
        name = lambda token: names.get(token, token)  # noqa: E731
        with self.lock:
            item = self.items.setdefault(Key["jobId"], {"jobId": Key["jobId"]})
            if ConditionExpression and not self._holds(ConditionExpression, item, name, values):
                raise ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": ""}}, "UpdateItem")
            for clause in re.split(r"\s+(?=SET |ADD )", UpdateExpression.strip()):
                verb, body = clause.split(" ", 1)
                for part in self._top_level(body):
                    if verb == "SET":
                        attr, val = (s.strip() for s in part.split("=", 1))
                        item[name(attr)] = self._value(val, item, name, values)
                    else:
                        attr, val = part.split()
                        item[name(attr)] = item.get(name(attr), 0) + values[val]

    @staticmethod
    def _top_level(body):
        """Split on commas outside parentheses (list_append(if_not_exists(a, b), c) is one part)."""
        parts, depth, cur = [], 0, ""
        for ch in body:
            depth += ch == "("
            depth -= ch == ")"
            if ch == "," and depth == 0:
                parts.append(cur)
                cur = ""
            else:
                cur += ch
        return [p.strip() for p in parts + [cur] if p.strip()]

    def _value(self, expr, item, name, values):
        """:placeholder, if_not_exists(#a, :b) or list_append(x, y): the subset the Lambdas use."""
        expr = expr.strip()
        m = re.fullmatch(r"(list_append|if_not_exists)\((.*)\)", expr)
        if not m:
            return values[expr]
        a, b = self._top_level(m.group(2))
        if m.group(1) == "if_not_exists":
            return item.get(name(a), self._value(b, item, name, values))
        return list(self._value(a, item, name, values)) + list(self._value(b, item, name, values))

    @staticmethod
    def _holds(cond, item, name, values):
        if "attribute_not_exists" in cond:  # rate counter: attribute_not_exists(#n) OR #n < :limit
            return item.get("n") is None or item["n"] < values[":limit"]
        if ":pending" in cond:  # worker claim
            s = item.get("status")
            return s == "PENDING" or (s == "RUNNING" and item.get("startedAtEpoch", 0) < values[":stale"])
        raise AssertionError("unexpected condition " + cond)


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, **kw):
        self.objects[Key] = Body


class FakeAgent:
    def invoke_agent_runtime(self, agentRuntimeArn, runtimeSessionId, payload):
        assert runtimeSessionId.startswith("cascade-") and len(runtimeSessionId) >= 33
        q = json.loads(payload)
        body = {"answer": "For a 30%% oil rise, %s's portfolio has historically moved about -0.8%%." % q["persona"],
                "toolCalls": [{"name": "get_portfolio_exposure", "input": {"persona": q["persona"]}, "output": "{}"},
                              {"name": "run_scenario", "input": {"persona": q["persona"], "oil_shock_pct": "30"},
                               "output": "{}"}],
                "citations": []}
        return {"response": io.BytesIO(json.dumps(body).encode())}


class FakeAthena:
    def __init__(self):
        self.sql = {}

    def start_query_execution(self, QueryString, **kw):
        qid = "q%d" % len(self.sql)
        self.sql[qid] = QueryString
        return {"QueryExecutionId": qid}

    def get_query_execution(self, QueryExecutionId):
        return {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}

    def get_query_results(self, QueryExecutionId, **kw):
        sql = self.sql[QueryExecutionId]
        if "FROM sensitivities" in sql:
            cols, rows = [("ticker", "varchar"), ("beta_simple", "double"), ("n_weeks", "bigint")], [["XIU.TO", "0.010571", "261"]]
        elif "max(week)" in sql:
            cols, rows = [("as_of", "varchar")], [["2026-11-13"]]
        else:
            cols, rows = [("ticker", "varchar")], []
        return {"ResultSet": {"ResultSetMetadata": {"ColumnInfo": [{"Name": n, "Type": t} for n, t in cols]},
                              "Rows": [{"Data": [{"VarCharValue": n} for n, _ in cols]}] +
                                      [{"Data": [{"VarCharValue": v} for v in r]} for r in rows]}}


class FakeSqs:
    """Delivers each message to the real worker handler on a background thread, like a Lambda trigger."""

    def __init__(self):
        self.threads = []

    def send_message(self, QueueUrl, MessageBody):
        record = {"messageId": "m%d" % len(self.threads), "body": MessageBody}
        t = threading.Thread(target=worker.lambda_handler, args=({"Records": [record]}, None))
        t.start()
        self.threads.append(t)


@pytest.fixture
def api(monkeypatch):
    table, s3, sqs = FakeDynamo(), FakeS3(), FakeSqs()
    for mod in (submit, status, worker):
        monkeypatch.setattr(mod, "_table", lambda: table)
    monkeypatch.setattr(submit, "_sqs", lambda: sqs)
    monkeypatch.setattr(worker, "_s3", lambda: s3)
    monkeypatch.setattr(worker, "_agent", lambda: FakeAgent())
    athena = FakeAthena()
    monkeypatch.setattr(research, "_athena", lambda: athena)
    research._cache.clear()
    for k, v in {"QUEUE_URL": "local", "AGENT_RUNTIME_ARN": "arn:local", "BUCKET": "local",
                 "ALLOWED_ORIGIN": ORIGIN}.items():
        monkeypatch.setenv(k, v)

    class Gateway(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _route(self, method):
            url = urllib.parse.urlsplit(self.path)
            length = int(self.headers.get("content-length") or 0)
            event = {"headers": {k.lower(): v for k, v in self.headers.items()},
                     "requestContext": {"http": {"method": method, "sourceIp": "127.0.0.1"}},
                     "queryStringParameters": dict(urllib.parse.parse_qsl(url.query)) or None,
                     "body": self.rfile.read(length).decode() if length else None}
            m = re.fullmatch(r"/jobs/([^/]+)", url.path)
            if method == "POST" and url.path == "/jobs":
                resp = submit.lambda_handler(event, None)
            elif method == "GET" and m:
                resp = status.lambda_handler(dict(event, pathParameters={"id": m.group(1)}), None)
            elif method == "GET" and url.path == "/research":
                resp = research.lambda_handler(event, None)
            else:
                resp = {"statusCode": 404, "headers": {}, "body": "{}"}
            self.send_response(resp["statusCode"])
            for k, v in resp["headers"].items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(resp["body"].encode())

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % server.server_port, table, s3, sqs
    server.shutdown()
    for t in sqs.threads:
        t.join(5)


def test_smoke_test_passes_end_to_end(api, capsys):
    url, table, s3, sqs = api
    code = smoke.main(["--api", url, "--origin", ORIGIN, "--poll", "0.05", "--timeout", "10"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "ALL CHECKS PASSED" in out and "status=DONE" in out
    jobs = [i for k, i in table.items.items() if not k.startswith("rate#")]
    assert len(jobs) == 1 and jobs[0]["status"] == "DONE" and len(jobs[0]["ownerHash"]) == 64
    assert any(k.startswith("rate#owner#") for k in table.items)
    assert list(s3.objects) == ["traces/%s.json" % jobs[0]["jobId"]]


def test_smoke_test_fails_when_the_job_fails(api, capsys, monkeypatch):
    url, *_ = api

    class Broken:
        def invoke_agent_runtime(self, **kw):
            raise RuntimeError("runtime not found")

    monkeypatch.setattr(worker, "_agent", lambda: Broken())
    code = smoke.main(["--api", url, "--poll", "0.05", "--timeout", "10", "--skip-research"])
    out = capsys.readouterr().out
    assert code == 1 and "FAIL job reached DONE" in out and "runtime not found" in out
