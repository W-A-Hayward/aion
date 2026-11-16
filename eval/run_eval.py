"""Eval v3 runner. See eval/README.md.

  python eval/run_eval.py                 all cases
  python eval/run_eval.py --only f1,a1    subset (case ids)
  python eval/run_eval.py --rerun-failed  failed or missing cases only

Env: API_URL (default https://wm28zdv834.execute-api.us-east-1.amazonaws.com). Needs AWS credentials for
Athena (workgroup cascade, database cascade): expected numbers and labels are read there at run time.
Writes eval/results.md and eval/results.json.
Each case uses its own random 48-char hex x-cascade-session. A 429 on submit waits 65 s and retries (max 3).
--rerun-failed reruns only cases that failed or never ran in eval/results.json and merges them back.
"""
import argparse
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grader  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CASES_PATH = os.path.join(HERE, "cases.yaml")
RESULTS_MD = os.path.join(HERE, "results.md")
RESULTS_JSON = os.path.join(HERE, "results.json")
DEFAULT_API_URL = "https://wm28zdv834.execute-api.us-east-1.amazonaws.com"
REGION = "us-east-1"
WORKGROUP = "cascade"
DATABASE = "cascade"
POLL_S = 4
RATE_LIMIT_WAIT_S = 65
RATE_LIMIT_RETRIES = 3
JOB_TIMEOUT_S = 150
ATHENA_TIMEOUT_S = 60
HTTP_TIMEOUT_S = 20
MAX_PARALLEL = 3
TYPE_ORDER = ("fact", "not_linked", "trap_advice", "trap_forecast", "must_answer")


# ----------------------------------------------------------------------------- cases
def load_cases(path=CASES_PATH):
    """cases.yaml holds one JSON flow mapping per list item; PyYAML is used when installed."""
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    try:
        import yaml
        rows = yaml.safe_load(raw)
    except ImportError:
        rows = []
        for line in raw.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                rows.append(json.loads(re.sub(r"^-\s*", "", line)))
    by_id = {}
    cases = []
    for row in rows:
        case = dict(by_id[row["repeat_of"]]) if row.get("repeat_of") else {}
        case.update({k: v for k, v in row.items() if k != "repeat_of"})
        case.setdefault("level", "expert")
        by_id[case["id"]] = case
        cases.append(case)
    return cases


# ----------------------------------------------------------------------------- HTTP
class ApiError(Exception):
    pass


def http(method, url, session, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "x-cascade-session": session, "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raise ApiError("HTTP %d %s" % (e.code, e.read().decode("utf-8", "replace")[:200]), e.code)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise ApiError("%s: %s" % (type(e).__name__, e), None)


def job_stage(resp):
    return str(resp.get("stage") or resp.get("status") or "").lower()


def run_job(api_url, session, case, sleep=time.sleep, clock=time.monotonic):
    """Submit, poll until done or failed. Returns (response, error, latency_s)."""
    started = clock()
    body = {"persona": case["persona"], "question": case["question"], "level": case["level"]}
    retries = 0
    while True:
        try:
            sub = http("POST", api_url + "/jobs", session, body)
            break
        except ApiError as e:
            if e.args[1] == 429 and retries < RATE_LIMIT_RETRIES:
                retries += 1
                sleep(RATE_LIMIT_WAIT_S)
                continue
            msg = "submit failed: %s" % e.args[0]
            if retries:
                msg += " (after %d retries on 429)" % retries
            return {}, msg, clock() - started
    job_id = sub.get("job_id") or sub.get("jobId") or sub.get("id")
    if not job_id:
        return sub, "submit returned no job id", clock() - started
    last_error = ""
    while True:
        try:
            resp = http("GET", "%s/jobs/%s" % (api_url, job_id), session)
            last_error = ""
            stage = job_stage(resp)
            if stage == "done":
                return resp, None, clock() - started
            if stage.startswith("fail"):
                return resp, "job failed (stage %s)" % stage, clock() - started
        except ApiError as e:
            resp = {}
            last_error = e.args[0]
            if e.args[1] is not None and 400 <= e.args[1] < 500:
                return resp, "poll failed: %s" % last_error, clock() - started
        if clock() - started + POLL_S > JOB_TIMEOUT_S:
            msg = "timeout after %ds" % JOB_TIMEOUT_S + (" (last error: %s)" % last_error if last_error else "")
            return resp, msg, clock() - started
        sleep(POLL_S)


# ----------------------------------------------------------------------------- Athena
_athena = None


def athena_rows(sql):
    """Run sql in workgroup cascade, db cascade. Returns a list of {column: value-or-None}."""
    global _athena
    if _athena is None:
        import boto3
        _athena = boto3.client("athena", region_name=REGION)
    qid = _athena.start_query_execution(
        QueryString=sql, WorkGroup=WORKGROUP, QueryExecutionContext={"Database": DATABASE})["QueryExecutionId"]
    deadline = time.monotonic() + ATHENA_TIMEOUT_S
    while True:
        st = _athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        if st["State"] == "SUCCEEDED":
            break
        if st["State"] in ("FAILED", "CANCELLED"):
            raise RuntimeError("athena %s: %s" % (st["State"], st.get("StateChangeReason", "")))
        if time.monotonic() > deadline:
            raise RuntimeError("athena timeout")
        time.sleep(1)
    rows = _athena.get_query_results(QueryExecutionId=qid, MaxResults=100)["ResultSet"]["Rows"]
    cells = [[c.get("VarCharValue") for c in r["Data"]] for r in rows]
    if not cells:
        return []
    header, body = cells[0], cells[1:]
    return [dict(zip(header, r)) for r in body]


def expected_for(case, query=athena_rows):
    if not case.get("sql"):
        return None
    rows = query(case["sql"])
    if not rows:
        raise RuntimeError("ground truth query returned no rows")
    return rows[0]


# ----------------------------------------------------------------------------- run
def new_session():
    return secrets.token_hex(24)


def run_case(case, api_url, session=None, query=athena_rows):
    """One session per case (48 hex chars), shared by its submit and status polls."""
    session = session or new_session()
    result = {"id": case["id"], "type": case["type"], "level": case["level"], "persona": case["persona"],
              "question": case["question"], "expected": None, "response": {}, "passed": False,
              "reason": "", "latency_s": 0.0}
    resp, error, latency = run_job(api_url, session, case)
    result["response"], result["latency_s"] = resp, round(latency, 1)
    if error:
        result["reason"] = error
        return result
    try:
        result["expected"] = expected_for(case, query)
    except Exception as e:  # ground truth missing: the case cannot be graded
        result["reason"] = "ground truth error: %s" % e
        return result
    reasons = grader.grade(case, resp, result["expected"])
    result["passed"] = not reasons
    result["reason"] = "; ".join(reasons)
    return result


def run_all(cases, api_url, session=None, query=athena_rows):
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        return list(pool.map(lambda c: run_case(c, api_url, session, query), cases))


# ----------------------------------------------------------------------------- report
def totals(results):
    by_type = {}
    for r in results:
        t = by_type.setdefault(r["type"], [0, 0])
        t[1] += 1
        t[0] += 1 if r["passed"] else 0
    order = [t for t in TYPE_ORDER if t in by_type] + [t for t in by_type if t not in TYPE_ORDER]
    return [(t, by_type[t][0], by_type[t][1]) for t in order]


def cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def write_reports(results, api_url, session=None, md_path=RESULTS_MD, json_path=RESULTS_JSON):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = ["# Eval v3 results", "", "Run: %s. API: %s" % (now, api_url), "",
             "| id | type | level | result | reason | latency (s) |", "|---|---|---|---|---|---|"]
    for r in results:
        lines.append("| %s | %s | %s | %s | %s | %.1f |" % (
            r["id"], r["type"], r["level"], "pass" if r["passed"] else "fail", cell(r["reason"]), r["latency_s"]))
    lines += ["", "## Totals per type", "", "| type | passed | total | rate |", "|---|---|---|---|"]
    for t, ok, n in totals(results):
        lines.append("| %s | %d | %d | %.0f%% |" % (t, ok, n, 100.0 * ok / n))
    ok_all, n_all = sum(r["passed"] for r in results), len(results)
    rate = 100.0 * ok_all / n_all if n_all else 0.0
    lines += ["", "## Overall", "", "Pass rate: %d/%d = %.1f%%" % (ok_all, n_all, rate), ""]
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"run_at": now, "api_url": api_url, "pass_rate": rate, "results": results}, f, indent=2,
                  ensure_ascii=False, default=str)
    return rate


def load_previous(path=RESULTS_JSON):
    try:
        with open(path, encoding="utf-8") as f:
            return {r["id"]: r for r in json.load(f).get("results", [])}
    except (OSError, ValueError, KeyError, AttributeError):
        return {}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run eval v3 against the cascade API.")
    ap.add_argument("--only", help="comma-separated case ids, e.g. f1,a1")
    ap.add_argument("--rerun-failed", action="store_true",
                    help="rerun only cases that failed or never ran in eval/results.json, then merge")
    args = ap.parse_args(argv)
    cases = load_cases()
    if args.only:
        wanted = [x.strip() for x in args.only.split(",") if x.strip()]
        unknown = [w for w in wanted if w not in {c["id"] for c in cases}]
        if unknown:
            ap.error("unknown case ids: %s" % ", ".join(unknown))
        cases = [c for c in cases if c["id"] in wanted]
    api_url = os.environ.get("API_URL", DEFAULT_API_URL).rstrip("/")
    if args.rerun_failed:
        previous = load_previous()
        todo = [c for c in cases if not previous.get(c["id"], {}).get("passed")]
        fresh = {r["id"]: r for r in run_all(todo, api_url)}
        results = [fresh.get(c["id"]) or previous[c["id"]] for c in cases if c["id"] in fresh or c["id"] in previous]
        print("Reran %d case(s)." % len(todo))
    else:
        results = run_all(cases, api_url)
    write_reports(results, api_url)
    ok = sum(r["passed"] for r in results)
    print("%d/%d passed. Wrote %s and %s" % (ok, len(results), RESULTS_MD, RESULTS_JSON))
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
