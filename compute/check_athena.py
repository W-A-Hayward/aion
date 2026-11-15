"""Check sensitivities.beta_simple against a regr_slope recomputation in Athena.

Usage (in SageMaker or any shell with AWS access): python compute/check_athena.py
Env:   BUCKET (default cascade-s3-bucket), ATHENA_OUTPUT (default s3://$BUCKET/athena-results/)

Steps:
1. If processed/weekly_returns/ has no objects, build the weekly returns with compute/stats.py
   (load_raw, build_weekly, build_subjects, weekly_returns_table) and write
   processed/weekly_returns/part-0.parquet (week, subject_or_ticker, ret_cad, brent_ret).
2. Create the Athena table weekly_returns if needed (check_athena.sql, statement create_weekly_returns).
3. Run recompute_beta_simple and stored_beta_simple, compare per ticker with tolerance 0.002 and
   print a table. Exit code 1 if any ticker differs or is missing.
"""
import io
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SQL_PATH = os.path.join(HERE, "check_athena.sql")

REGION = "us-east-1"
DEFAULT_BUCKET = "cascade-s3-bucket"
DATABASE = "cascade"
WORKGROUP = "cascade"
TOLERANCE = 0.002
TICKERS = ("XOM", "TLT", "ENB.TO", "QQQ", "RY.TO")
WEEKLY_PREFIX = "processed/weekly_returns/"
WEEKLY_KEY = WEEKLY_PREFIX + "part-0.parquet"
POLL_SECONDS = 1.0
POLL_TIMEOUT = 120.0


# ----------------------------------------------------------------------------- pure helpers

def load_statements(path=SQL_PATH):
    """Statements of the SQL file by name. A statement starts at a "-- name: x" line and ends at ';'."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    out = {}
    for m in re.finditer(r"^-- name:\s*(\w+)\s*$(.*?);", text, re.MULTILINE | re.DOTALL):
        body = "\n".join(l for l in m.group(2).splitlines() if not l.strip().startswith("--")).strip()
        out[m.group(1)] = body
    return out


def compare_betas(recomputed, stored, tolerance=TOLERANCE, tickers=TICKERS):
    """Compare {ticker: beta} dicts. Returns {"pass", "rows"}; each row has ticker, stored, recomputed,
    diff and ok. A ticker missing from either side, or with a null value, fails."""
    rows = []
    for t in tickers:
        a, b = stored.get(t), recomputed.get(t)
        if a is None or b is None:
            rows.append({"ticker": t, "stored": a, "recomputed": b, "diff": None, "ok": False})
            continue
        diff = abs(a - b)
        rows.append({"ticker": t, "stored": a, "recomputed": b, "diff": diff, "ok": diff <= tolerance + 1e-12})
    return {"pass": all(r["ok"] for r in rows), "rows": rows}


def format_rows(result):
    lines = ["%-8s %12s %12s %10s  %s" % ("ticker", "stored", "recomputed", "diff", "ok")]
    for r in result["rows"]:
        f = lambda v: "-" if v is None else "%.6f" % v
        lines.append("%-8s %12s %12s %10s  %s" % (r["ticker"], f(r["stored"]), f(r["recomputed"]),
                                                  f(r["diff"]), "ok" if r["ok"] else "FAIL"))
    return "\n".join(lines)


def betas_by_ticker(rows, column):
    out = {}
    for r in rows:
        try:
            out[r["ticker"]] = float(r[column])
        except (TypeError, ValueError, KeyError):
            out[r["ticker"]] = None
    return out


# ----------------------------------------------------------------------------- AWS (not used in tests)

def weekly_returns_exists(s3, bucket):
    resp = s3.list_objects_v2(Bucket=bucket, Prefix=WEEKLY_PREFIX, MaxKeys=1)
    return resp.get("KeyCount", 0) > 0


def write_weekly_returns(s3, bucket):
    """Build the weekly returns from the raw files with compute/stats.py and write them to processed/."""
    try:
        from compute import stats
    except ImportError:
        import stats
    data = stats.build_weekly(stats.load_raw(bucket, s3))
    table = stats.weekly_returns_table(data, stats.build_subjects(data))
    buf = io.BytesIO()
    table.to_parquet(buf, index=False)
    s3.put_object(Bucket=bucket, Key=WEEKLY_KEY, Body=buf.getvalue())
    return len(table)


def run_query(athena, sql, output):
    qid = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": DATABASE},
        WorkGroup=WORKGROUP,
        ResultConfiguration={"OutputLocation": output},
    )["QueryExecutionId"]
    deadline = time.monotonic() + POLL_TIMEOUT
    while True:
        status = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        if status["State"] == "SUCCEEDED":
            break
        if status["State"] in ("FAILED", "CANCELLED"):
            raise RuntimeError("athena query %s: %s" % (status["State"].lower(), status.get("StateChangeReason", "")))
        if time.monotonic() >= deadline:
            raise RuntimeError("athena query timed out")
        time.sleep(POLL_SECONDS)
    rows, header, token = [], None, None
    while True:
        kwargs = {"QueryExecutionId": qid}
        if token:
            kwargs["NextToken"] = token
        page = athena.get_query_results(**kwargs)
        for r in page["ResultSet"]["Rows"]:
            cells = [c.get("VarCharValue") for c in r["Data"]]
            if header is None:
                header = cells
            else:
                rows.append(dict(zip(header, cells)))
        token = page.get("NextToken")
        if not token:
            return rows


def main():
    import boto3
    bucket = os.environ.get("BUCKET", DEFAULT_BUCKET)
    output = os.environ.get("ATHENA_OUTPUT", "s3://%s/athena-results/" % bucket)
    s3 = boto3.client("s3", region_name=REGION)
    athena = boto3.client("athena", region_name=REGION)
    sql = load_statements()

    if weekly_returns_exists(s3, bucket):
        print("processed/weekly_returns/ exists; using it")
    else:
        print("processed/weekly_returns/ not found; building it from compute/stats.py")
        print("wrote %d rows to s3://%s/%s" % (write_weekly_returns(s3, bucket), bucket, WEEKLY_KEY))
    run_query(athena, sql["create_weekly_returns"], output)

    recomputed = betas_by_ticker(run_query(athena, sql["recompute_beta_simple"], output), "beta_recomputed")
    stored = betas_by_ticker(run_query(athena, sql["stored_beta_simple"], output), "beta_simple")
    result = compare_betas(recomputed, stored)
    print(format_rows(result))
    print("PASS: all within %g" % TOLERANCE if result["pass"] else "FAIL: see rows marked FAIL (tolerance %g)" % TOLERANCE)
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
