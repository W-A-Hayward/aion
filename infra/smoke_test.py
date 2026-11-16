"""End-to-end smoke test for a deployed cascade API. Standard library only.

    python3 infra/smoke_test.py --api https://abc123.execute-api.us-east-1.amazonaws.com \
        --origin https://your-frontend.example

Checks, in order, and exits 0 only if every check passes:
  1. GET /research?ticker=XIU.TO returns the table envelope with an XIU.TO sensitivity row.
  2. POST /jobs without a session token is rejected (401).
  3. POST /jobs with a token is accepted (202) and returns a jobId.
  4. GET /jobs/{id} with a DIFFERENT token returns 404 (jobs are private to their owner).
  5. Polling GET /jobs/{id} reaches DONE with a non-empty answer and at least one tool call
     (proves submit -> SQS -> worker -> AgentCore -> tools Lambda -> Athena -> DynamoDB).
With --origin, every response must also carry access-control-allow-origin for that origin.
"""
import argparse
import json
import secrets
import sys
import time
import urllib.error
import urllib.request

QUESTION = "How exposed is my portfolio to a 30% rise in oil, and which holding matters most?"


class Check:
    def __init__(self):
        self.failed = 0

    def __call__(self, ok, label, detail=""):
        print("%s %s%s" % ("PASS" if ok else "FAIL", label, (" - " + detail) if detail else ""))
        if not ok:
            self.failed += 1
        return ok


def request(method, url, token=None, body=None, origin=None, timeout=30):
    headers = {"Accept": "application/json"}
    if token:
        headers["X-Cascade-Session"] = token
    if origin:
        headers["Origin"] = origin
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, raw, resp_headers = r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        status, raw, resp_headers = e.code, e.read(), e.headers
    try:
        payload = json.loads(raw or b"null")
    except ValueError:
        payload = {"raw": raw[:300].decode("utf-8", "replace")}
    return status, payload, {k.lower(): v for k, v in resp_headers.items()}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api", required=True, help="API base URL, no trailing slash")
    p.add_argument("--origin", help="frontend origin to verify CORS for")
    p.add_argument("--persona", default="robert", choices=["robert", "amira", "mateo"])
    p.add_argument("--timeout", type=float, default=240, help="seconds to wait for DONE")
    p.add_argument("--poll", type=float, default=2.0)
    p.add_argument("--skip-research", action="store_true")
    a = p.parse_args(argv)
    api = a.api.rstrip("/")
    check = Check()

    def cors_ok(headers):
        return not a.origin or headers.get("access-control-allow-origin") in (a.origin, "*")

    if not a.skip_research:
        status, body, h = request("GET", api + "/research?ticker=XIU.TO", origin=a.origin)
        rows = body.get("sensitivities") if isinstance(body, dict) else None
        check(status == 200 and isinstance(rows, list) and any(r.get("ticker") == "XIU.TO" for r in rows),
              "research endpoint returns XIU.TO", "HTTP %s" % status)
        if isinstance(body, dict) and isinstance(body.get("meta"), dict):
            print("     as_of=%s missing=%s" % (body["meta"].get("as_of"), body["meta"].get("missing")))
        check(cors_ok(h), "research CORS header", str(h.get("access-control-allow-origin")))

    job = {"question": QUESTION, "persona": a.persona, "level": "beginner"}
    status, body, _ = request("POST", api + "/jobs", body=job, origin=a.origin)
    check(status == 401, "submit without a session token is rejected", "HTTP %s" % status)

    token, stranger = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    status, body, h = request("POST", api + "/jobs", token=token, body=job, origin=a.origin)
    job_id = body.get("jobId") if isinstance(body, dict) else None
    if not check(status == 202 and job_id, "submit accepted", "HTTP %s %s" % (status, body)):
        return 1
    check(cors_ok(h), "submit CORS header", str(h.get("access-control-allow-origin")))
    print("     jobId=%s" % job_id)

    status, _, _ = request("GET", "%s/jobs/%s" % (api, job_id), token=stranger)
    check(status == 404, "another browser cannot read the job", "HTTP %s" % status)

    deadline, last, started = time.time() + a.timeout, None, time.time()
    while True:
        status, body, h = request("GET", "%s/jobs/%s" % (api, job_id), token=token, origin=a.origin)
        state = body.get("status") if isinstance(body, dict) else None
        if state != last:
            print("     %5.1fs status=%s" % (time.time() - started, state or "HTTP %s" % status))
            last = state
        if state in ("DONE", "FAILED") or time.time() > deadline or status != 200:
            break
        time.sleep(a.poll)

    calls = body.get("toolCalls") or [] if isinstance(body, dict) else []
    check(state == "DONE", "job reached DONE", body.get("error", "") if isinstance(body, dict) else "")
    if state == "DONE":
        answer = body.get("answer")
        # docs/api_contract.md: answer is {verdict, headline, text, refusal, caveat}; older jobs return a string.
        text = (answer.get("text") or "") if isinstance(answer, dict) else (answer or "")
        refused = isinstance(answer, dict) and answer.get("refusal") is True
        check(bool(text.strip()) or refused, "answer is not empty")
        check(len(calls) > 0, "agent called at least one tool", ", ".join(c.get("name", "?") for c in calls))
        check(cors_ok(h), "status CORS header", str(h.get("access-control-allow-origin")))
        print("     durationMs=%s citations=%d" % (body.get("durationMs"), len(body.get("citations") or [])))
        verdict = answer.get("verdict") if isinstance(answer, dict) else None
        print("     answer: %s%s" % ("[%s] " % verdict if verdict else "", text[:400].replace("\n", " ")))
    print("\n%s" % ("ALL CHECKS PASSED" if not check.failed else "%d CHECK(S) FAILED" % check.failed))
    return 1 if check.failed else 0


if __name__ == "__main__":
    sys.exit(main())
