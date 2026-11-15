"""Run eval/questions.json against a deployed cascade API and score each answer. Standard library only.

    python3 eval/run_eval.py --api https://abc123.execute-api.us-east-1.amazonaws.com [--only id1,id2]

Each question is submitted through POST /jobs and polled on GET /jobs/{id}. The checks are
deterministic and coarse (tool names, required/forbidden phrases, word limits); a human should still
read the answers. Exit code 0 only if every selected question passes. Submissions are paced to
respect the per-owner rate limit (429 responses are retried after Retry-After).
"""
import argparse
import json
import os
import re
import secrets
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "infra"))
from smoke_test import request  # noqa: E402

QUESTIONS = os.path.join(os.path.dirname(__file__), "questions.json")


def score(case, result):
    """Return a list of failure messages for one finished job (empty = pass)."""
    exp, fails = case["expect"], []
    if result.get("status") != "DONE":
        return ["job ended %s: %s" % (result.get("status"), result.get("error"))]
    answer = result.get("answer") or ""
    low = answer.lower()
    tools = [c.get("name") for c in result.get("toolCalls") or [] if isinstance(c, dict)]
    for t in exp.get("tools_required", []):
        if t not in tools:
            fails.append("tool %s not called (called: %s)" % (t, ", ".join(tools) or "none"))
    if exp.get("tools_any") and not set(exp["tools_any"]) & set(tools):
        fails.append("none of %s called" % exp["tools_any"])
    if exp.get("must_include_any") and not any(s.lower() in low for s in exp["must_include_any"]):
        fails.append("missing any of %s" % exp["must_include_any"])
    for s in exp.get("must_include_all", []):
        if s.lower() not in low:
            fails.append("missing %r" % s)
    for pattern in exp.get("must_not_match", []):
        m = re.search(pattern, answer, re.I)
        if m:
            fails.append("forbidden text %r" % m.group(0))
    words = len(answer.split())
    if exp.get("max_words") and words > exp["max_words"] * 1.15:  # 15% slack: word counts are fuzzy
        fails.append("%d words > %d" % (words, exp["max_words"]))
    if exp.get("requires_citations") and not result.get("citations"):
        fails.append("no citations")
    return fails


def ask(api, token, case, timeout):
    body = {"question": case["question"], "persona": case["persona"], "level": case["level"]}
    while True:
        status, job, headers = request("POST", api + "/jobs", token=token, body=body)
        if status != 429:
            break
        time.sleep(int(headers.get("retry-after", "60")))
    if status != 202:
        return {"status": "SUBMIT_FAILED", "error": "HTTP %s %s" % (status, job)}
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, result, _ = request("GET", "%s/jobs/%s" % (api, job["jobId"]), token=token)
        if status == 200 and result.get("status") in ("DONE", "FAILED"):
            return result
        time.sleep(2)
    return {"status": "TIMEOUT", "error": "no result after %ss" % timeout}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api", required=True)
    p.add_argument("--only", help="comma-separated question ids")
    p.add_argument("--timeout", type=float, default=240)
    p.add_argument("--out", help="write full answers and scores to this JSON file")
    a = p.parse_args(argv)
    cases = json.load(open(QUESTIONS))
    if a.only:
        wanted = set(a.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    token, report, failed = secrets.token_urlsafe(32), [], 0
    for case in cases:
        result = ask(a.api.rstrip("/"), token, case, a.timeout)
        fails = score(case, result)
        failed += bool(fails)
        print("%s %-26s %s" % ("PASS" if not fails else "FAIL", case["id"], "; ".join(fails)))
        report.append({"id": case["id"], "pass": not fails, "fails": fails, "result": result})
    if a.out:
        json.dump(report, open(a.out, "w"), indent=2, default=str)
    print("\n%d/%d passed" % (len(cases) - failed, len(cases)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
