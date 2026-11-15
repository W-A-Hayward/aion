"""Markdown report from an eval results file.

Usage: python eval/report.py [eval/results/<timestamp>.jsonl]   (default: latest file in eval/results)
Writes eval/results/<timestamp>.md and uploads it to s3://$BUCKET/eval/<timestamp>/report.md.
Env: BUCKET (default cascade-s3-bucket).

Pass = job DONE, every automatic check passes, and no judge score is below 3.
Latency is wall-clock time from POST /jobs to DONE (timeouts count as 120 s).
"""
import json
import math
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(HERE, "results")
DEFAULT_BUCKET = "cascade-s3-bucket"
REGION = "us-east-1"
PERSONAS = ("robert", "amira", "mateo")
LEVELS = ("beginner", "expert")
JUDGE_KEYS = ("grounded", "level_fit", "persona_fit", "safety", "clarity")
QUESTION_WIDTH = 70


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def percentile(values, p):
    """Nearest-rank percentile; None for an empty list."""
    if not values:
        return None
    s = sorted(values)
    return s[max(0, math.ceil(p / 100 * len(s)) - 1)]


def mean_score(records, key):
    scores = [r["judge"]["scores"][key]["score"] for r in records
              if r.get("judge") and "scores" in r["judge"]]
    return sum(scores) / len(scores) if scores else None


def fmt(x, nd=1):
    return "-" if x is None else ("%.*f" % (nd, x))


def secs(ms):
    return "-" if ms is None else "%.1f" % (ms / 1000)


def cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def short(text, n=QUESTION_WIDTH):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 3] + "..."


def summary_row(label, records):
    n = len(records)
    passed = sum(1 for r in records if r.get("pass"))
    lat = [r["wallMs"] for r in records if r.get("wallMs") is not None]
    cols = [label, str(n), "%d/%d (%d%%)" % (passed, n, round(100 * passed / n) if n else 0)]
    cols += [fmt(mean_score(records, k)) for k in JUDGE_KEYS]
    cols += [secs(statistics.median(lat) if lat else None), secs(percentile(lat, 90))]
    return "| " + " | ".join(cols) + " |"


def build_report(records, run_id):
    lines = ["# cascade evaluation", "", "Run: `%s`. Questions: %d. Pass: %d/%d." % (
        run_id, len(records), sum(1 for r in records if r.get("pass")), len(records)), ""]
    header = ["Group", "N", "Pass rate", "Grounded", "Level fit", "Persona fit", "Safety", "Clarity",
              "Median s", "p90 s"]
    sep = "|" + "|".join("---" for _ in header) + "|"
    head = "| " + " | ".join(header) + " |"
    lines += ["Judge scores are means on a 1-5 scale. Latency is end to end, in seconds.", ""]

    for persona in PERSONAS:
        recs = [r for r in records if r["persona"] == persona]
        lines += ["## %s" % persona.capitalize(), "", head, sep]
        for level in LEVELS:
            lines.append(summary_row(level, [r for r in recs if r["level"] == level]))
        lines += [summary_row("all", recs), ""]
        lines += ["| Id | Level | Question | Result | Seconds | Grounded | Level fit | Persona fit | Safety | Clarity |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for r in recs:
            scores = r["judge"]["scores"] if r.get("judge") and "scores" in r["judge"] else {}
            sc = [str(scores[k]["score"]) if k in scores else "-" for k in JUDGE_KEYS]
            lines.append("| " + " | ".join(
                [cell(r["id"]), r["level"], cell(short(r["question"])), "PASS" if r.get("pass") else "FAIL",
                 secs(r.get("wallMs"))] + sc) + " |")
        lines.append("")

    lines += ["## Overall", "", head, sep, summary_row("all", records), ""]

    failed = [r for r in records if not r.get("pass")]
    lines += ["## Failed questions", ""]
    if not failed:
        lines.append("None.")
    for r in failed:
        lines.append("- **%s** (%s, %s): %s" % (r["id"], r["persona"], r["level"],
                                                cell("; ".join(r.get("reasons") or ["no reason recorded"]))))
    lines.append("")
    return "\n".join(lines)


def latest_results():
    files = sorted(f for f in os.listdir(RESULTS_DIR) if f.endswith(".jsonl"))
    if not files:
        sys.exit("no .jsonl files in " + RESULTS_DIR)
    return os.path.join(RESULTS_DIR, files[-1])


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else latest_results()
    run_id = os.path.basename(path)[: -len(".jsonl")]
    records = load(path)
    md = build_report(records, run_id)
    out = os.path.join(os.path.dirname(os.path.abspath(path)), run_id + ".md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    bucket = os.environ.get("BUCKET", DEFAULT_BUCKET)
    import boto3
    boto3.client("s3", region_name=REGION).upload_file(out, bucket, "eval/%s/report.md" % run_id)
    print("wrote %s and s3://%s/eval/%s/report.md" % (out, bucket, run_id))


if __name__ == "__main__":
    main()
