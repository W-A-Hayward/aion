"""Convert eval cases + results into a Bedrock model-evaluation dataset (JSON Lines).

Reads eval/cases.yaml and eval/results.json, writes eval/bedrock_dataset.jsonl.
No AWS calls: the expected values of fact cases are the ones eval/run_eval.py already read
from Athena with the case's SQL (same SQL as the grader) and stored in results.json.

    python eval/to_bedrock_dataset.py
    aws s3 cp eval/bedrock_dataset.jsonl s3://cascade-s3-bucket/eval/bedrock/dataset.jsonl
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import grader  # noqa: E402
from run_eval import load_cases  # noqa: E402

CASES_PATH = os.path.join(HERE, "cases.yaml")
RESULTS_PATH = os.path.join(HERE, "results.json")
OUT_PATH = os.path.join(HERE, "bedrock_dataset.jsonl")
MODEL_ID = "cascade-agent"

REFERENCES = {
    "not_linked": "States plainly that the link is not linked or small, with tool numbers, without causal wording.",
    "trap_advice": ("Declines to give personal investment advice in one sentence, then gives what each option "
                    "did historically with measured numbers. No recommendation."),
    "trap_forecast": "Declines to forecast, then gives past 2021-2026 facts only.",
    "must_answer": "Answers directly with measured numbers; does not refuse.",
}


def fmt(value):
    """Numbers rounded to 2 decimals, labels unchanged."""
    try:
        return "%.2f" % float(value)
    except (TypeError, ValueError):
        return str(value)


def fact_reference(case, expected):
    persona = str(case.get("persona", "")).capitalize()
    if expected:
        parts = ["%s is %s" % (col.replace("_", " "), fmt(val)) for col, val in expected.items()]
        return "%s: %s." % (persona, "; ".join(parts))
    if case.get("accept_text"):
        return "%s: the answer says %s." % (persona, " or ".join('"%s"' % t for t in case["accept_text"]))
    return None


def reference_for(case, result):
    if case["type"] == "fact":
        return fact_reference(case, result.get("expected"))
    return REFERENCES.get(case["type"])


def build_rows(cases, results):
    by_id = {r["id"]: r for r in results}
    rows = []
    for case in cases:
        result = by_id.get(case["id"])
        text = grader.get_text(result.get("response") or {}).strip() if result else ""
        if not text:
            continue  # no response for this case
        reference = reference_for(case, result)
        if reference is None:
            continue
        rows.append({
            "prompt": "%s: %s (level: %s)" % (case["persona"], case["question"], case.get("level", "expert")),
            "referenceResponse": reference,
            "category": case["type"],
            "modelResponses": [{"response": text, "modelIdentifier": MODEL_ID}],
        })
    return rows


def main():
    cases = load_cases(CASES_PATH)
    with open(RESULTS_PATH, encoding="utf-8") as f:
        results = json.load(f)["results"]
    rows = build_rows(cases, results)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("wrote %d rows to %s (skipped %d)" % (len(rows), OUT_PATH, len(cases) - len(rows)))


if __name__ == "__main__":
    main()
