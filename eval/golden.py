"""Build eval/golden.json: expected values for every question in questions.json, read from Athena.

Usage: python eval/golden.py        (reads Athena workgroup cascade, database cascade; writes eval/golden.json)
Env:   ATHENA_OUTPUT  result location (default s3://cascade-s3-bucket/athena-results/)

Per question (keyed by id):
  persona, level
  tickers           persona holdings and alternatives, plus tickers named in the question text,
                    must_mention or expected_label
  allowed_tickers   persona holdings and alternatives (the tickers an answer may mention)
  alternatives      [holding, alternative] pairs of the persona
  labels            {ticker: label}                     from confidence
  betas             {ticker: beta_simple}               from sensitivities
  portfolio_beta    {beta, lo, hi}                      from portfolio_beta
  verdicts          {ticker or persona: verdict}        from materiality, only when that table exists
  impacts           {"ticker|TLT|30": impact_pct, ...}  from scenarios (persona and ticker rows, 4 shocks)
Top level: generated_at, universe (tickers in sensitivities), evidence_urls (distinct source_url in evidence),
materiality ("used" or a reason it was not).

The materiality table (stats.materiality: subject, subject_type, verdict, ...) is read only if it exists in
the Glue database; otherwise verdicts is empty and "materiality" says why.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import run_eval

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN_PATH = os.path.join(HERE, "golden.json")

REGION = "us-east-1"
DATABASE = "cascade"
WORKGROUP = "cascade"
DEFAULT_OUTPUT = "s3://cascade-s3-bucket/athena-results/"
POLL_SECONDS = 1.0
POLL_TIMEOUT = 120.0

QUERIES = {
    "sensitivities": "SELECT ticker, beta_simple FROM sensitivities",
    "confidence": "SELECT ticker, label FROM confidence",
    "portfolio_beta": "SELECT persona, beta, lo, hi FROM portfolio_beta",
    "persona_holdings": "SELECT persona, ticker, weight FROM persona_holdings",
    "alternatives": "SELECT persona, holding, alternative FROM alternatives",
    "scenarios": "SELECT subject, subject_type, shock_pct, impact_pct FROM scenarios",
    "evidence_urls": "SELECT DISTINCT source_url FROM evidence WHERE source_url IS NOT NULL",
}
MATERIALITY_EXISTS = ("SELECT table_name FROM information_schema.tables "
                      "WHERE table_schema = 'cascade' AND table_name = 'materiality'")
MATERIALITY_ROWS = "SELECT subject, verdict FROM materiality"

_NUMBER = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")


# ----------------------------------------------------------------------------- Athena

def convert(value):
    """Athena returns text. Numbers become floats; NaN and empty become None."""
    if value is None or value == "" or value.lower() == "nan":
        return None
    return float(value) if _NUMBER.fullmatch(value) else value


def run_query(client, sql):
    """Run one SELECT in workgroup cascade, database cascade. Returns a list of dicts."""
    qid = client.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": DATABASE},
        WorkGroup=WORKGROUP,
        ResultConfiguration={"OutputLocation": os.environ.get("ATHENA_OUTPUT", DEFAULT_OUTPUT)},
    )["QueryExecutionId"]
    deadline = time.monotonic() + POLL_TIMEOUT
    while True:
        status = client.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        if status["State"] == "SUCCEEDED":
            break
        if status["State"] in ("FAILED", "CANCELLED"):
            raise RuntimeError("athena query %s: %s (%s)" % (
                status["State"].lower(), status.get("StateChangeReason", ""), sql[:80]))
        if time.monotonic() >= deadline:
            raise RuntimeError("athena query timed out: " + sql[:80])
        time.sleep(POLL_SECONDS)
    rows, header, token = [], None, None
    while True:
        kwargs = {"QueryExecutionId": qid}
        if token:
            kwargs["NextToken"] = token
        page = client.get_query_results(**kwargs)
        for r in page["ResultSet"]["Rows"]:
            cells = [c.get("VarCharValue") for c in r["Data"]]
            if header is None:
                header = cells
            else:
                rows.append({h: convert(c) for h, c in zip(header, cells)})
        token = page.get("NextToken")
        if not token:
            return rows


def fetch_tables(client):
    """Read every table the golden file needs. materiality is read only if it exists."""
    tables = {name: run_query(client, sql) for name, sql in QUERIES.items()}
    tables["materiality"] = None
    if run_query(client, MATERIALITY_EXISTS):
        tables["materiality"] = run_query(client, MATERIALITY_ROWS)
    return tables


# ----------------------------------------------------------------------------- golden values

def verdicts_from_materiality(rows):
    """({ticker or persona: verdict}, status). Rows follow stats.materiality: `subject` (ticker or persona) and `verdict`."""
    if rows is None:
        return {}, "table materiality does not exist"
    out = {}
    for r in rows:
        key = r.get("subject") if r.get("subject") is not None else r.get("ticker")
        if key is not None and r.get("verdict") is not None:
            out[key] = r["verdict"]
    if rows and not out:
        return {}, "table materiality has no usable rows (needs subject and verdict)"
    return out, "used"


def question_tickers(question, universe):
    """Tickers named in the question text, must_mention or expected_label."""
    expect = question.get("expect") or {}
    texts = [question.get("question", "")]
    for entry in expect.get("must_mention", []):
        texts.extend(entry.split("|"))
    found = run_eval.find_tickers(" ".join(texts), universe)
    found |= {t for t in (expect.get("expected_label") or {}) if t in universe}
    return found


def _impact_in_scope(key, persona, tickers):
    kind, subject, _ = key.split("|")
    return subject == persona if kind == "persona" else subject in tickers


def build_golden(questions, tables, generated_at=None):
    sens = {r["ticker"]: r["beta_simple"] for r in tables["sensitivities"] if r.get("beta_simple") is not None}
    universe = sorted({r["ticker"] for r in tables["sensitivities"]})
    labels = {r["ticker"]: r["label"] for r in tables["confidence"] if r.get("label") is not None}
    pbeta = {r["persona"]: {"beta": r["beta"], "lo": r["lo"], "hi": r["hi"]} for r in tables["portfolio_beta"]}
    verdicts, materiality = verdicts_from_materiality(tables.get("materiality"))
    impacts = {}
    for r in tables["scenarios"]:
        if r.get("impact_pct") is not None and r.get("shock_pct") is not None:
            kind = "persona" if r["subject_type"] == "persona" else "ticker"
            impacts["%s|%s|%d" % (kind, r["subject"], int(r["shock_pct"]))] = r["impact_pct"]

    out = {}
    for q in questions:
        persona = q["persona"]
        holdings = sorted({r["ticker"] for r in tables["persona_holdings"] if r["persona"] == persona})
        pairs = sorted([r["holding"], r["alternative"]] for r in tables["alternatives"] if r["persona"] == persona)
        allowed = sorted(set(holdings) | {t for pair in pairs for t in pair})
        tickers = sorted(set(allowed) | question_tickers(q, universe))
        out[q["id"]] = {
            "persona": persona,
            "level": q["level"],
            "tickers": tickers,
            "allowed_tickers": allowed,
            "alternatives": pairs,
            "labels": {t: labels[t] for t in tickers if t in labels},
            "betas": {t: sens[t] for t in tickers if t in sens},
            "portfolio_beta": pbeta.get(persona),
            "verdicts": {k: v for k, v in verdicts.items() if k in tickers or k == persona},
            "impacts": {k: v for k, v in impacts.items() if _impact_in_scope(k, persona, tickers)},
        }
    return {
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "universe": universe,
        "evidence_urls": sorted(r["source_url"] for r in tables["evidence_urls"]),
        "materiality": materiality,
        "questions": out,
    }


def main():
    import boto3
    client = boto3.client("athena", region_name=REGION)
    questions = run_eval.load_questions()
    golden = build_golden(questions, fetch_tables(client))
    with open(GOLDEN_PATH, "w", encoding="utf-8") as f:
        json.dump(golden, f, indent=2, sort_keys=True)
        f.write("\n")
    print("wrote %s: %d questions, %d tickers, %d evidence urls, materiality: %s" % (
        GOLDEN_PATH, len(golden["questions"]), len(golden["universe"]), len(golden["evidence_urls"]),
        golden["materiality"]))


if __name__ == "__main__":
    sys.exit(main())
