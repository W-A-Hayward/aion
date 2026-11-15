"""Markdown report from an eval results file.

Usage: python eval/report.py [eval/results/<timestamp>.jsonl]   (default: latest file in eval/results)
Writes eval/results/<timestamp>.md and uploads it to s3://$BUCKET/eval/<timestamp>/report.md.
Env: BUCKET (default cascade-s3-bucket).

Sections: factual accuracy, faithfulness, trajectory, consistency (from <timestamp>.consistency.json next to the
results file, when present), answer content, judge.
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


def check_details(check):
    """Problem strings of one stored check, whatever its shape."""
    if not isinstance(check, dict):
        return []
    if check.get("problems"):
        return [str(p) for p in check["problems"]]
    out = [str(m) for m in check.get("missing") or []]
    out += [str(m) for m in check.get("found") or []]
    for key in ("flagged", "sign_flagged", "other_flagged"):
        out += [str(m) for m in check.get(key) or []]
    return out


def check_table(records, rows):
    """Table of automatic checks. rows: (title, check key). A record counts only if it has that check."""
    lines = ["| Check | Passed | Evaluated |", "|---|---|---|"]
    for title, key in rows:
        have = [r for r in records if (r.get("checks") or {}).get(key)]
        ok = sum(1 for r in have if r["checks"][key].get("pass"))
        lines.append("| %s | %s | %d |" % (title, ok if have else "-", len(have)))
    return lines


def check_failures(records, keys):
    lines = []
    for r in records:
        for key in keys:
            check = (r.get("checks") or {}).get(key)
            if check and not check.get("pass"):
                lines.append("- **%s** (%s): %s" % (r["id"], key, cell("; ".join(check_details(check)) or "failed")))
    return lines or ["No failures."]


def claim_totals(records):
    checked = sum((r["checks"].get("claims") or {}).get("checked", 0) for r in records if r.get("checks"))
    unchecked = sum(len((r["checks"].get("claims") or {}).get("unchecked", [])) for r in records if r.get("checks"))
    sources = {}
    for r in records:
        if r.get("claimsSource"):
            sources[r["claimsSource"]] = sources.get(r["claimsSource"], 0) + 1
    return checked, unchecked, sources


def pct(agree, total):
    return "-" if not total else "%d/%d (%d%%)" % (agree, total, round(100 * agree / total))


def consistency_lines(consistency):
    if not consistency:
        return ["No consistency results for this run."]
    summary = consistency.get("summary", consistency)
    lines = ["### Paraphrase and other level", "",
             "Each variant is compared with the main run of the same question, over tickers both runs state. "
             "Compared = tickers with a label (or verdict) in both runs.", "",
             "| Question | Variant | Status | Label agreement | Verdict agreement | Disagreements |",
             "|---|---|---|---|---|---|"]
    totals = {"label": [0, 0], "verdict": [0, 0]}
    for p in summary.get("pairs", []):
        if p.get("status") != "DONE" or "label" not in p:
            lines.append("| %s | %s | %s | - | - | %s |" % (cell(p["id"]), p["kind"], p.get("status"),
                                                           cell(p.get("error") or "")))
            continue
        for f in totals:
            totals[f][0] += p[f]["agree"]
            totals[f][1] += p[f]["compared"]
        lines.append("| %s | %s | DONE | %s | %s | %s |" % (
            cell(p["id"]), p["kind"], pct(p["label"]["agree"], p["label"]["compared"]),
            pct(p["verdict"]["agree"], p["verdict"]["compared"]),
            cell(", ".join(p["label"]["disagree"] + p["verdict"]["disagree"]) or "none")))
    lines += ["", "Overall label agreement: %s. Overall verdict agreement: %s." % (
        pct(*totals["label"]), pct(*totals["verdict"])), "", "### Repeats", "",
        "| Question | Runs | Labels stable | Verdicts stable | Numbers stable | Max number spread | Unstable or partial |",
        "|---|---|---|---|---|---|---|"]
    for rep in summary.get("repeats", []):
        st = rep.get("stability")
        if not st:
            lines.append("| %s | 0/%d | - | - | - | - | %s |" % (cell(rep["id"]), rep["requested"],
                                                              cell("; ".join(rep.get("errors") or []))))
            continue
        odd = []
        for f in ("label", "verdict", "numbers"):
            odd += ["%s %s" % (f, k) for k in st[f]["unstable"] + st[f]["partial"]]
        lines.append("| %s | %d/%d | %s | %s | %s | %.4f | %s |" % (
            cell(rep["id"]), rep["runs"], rep["requested"], pct(st["label"]["stable"], st["label"]["total"]),
            pct(st["verdict"]["stable"], st["verdict"]["total"]),
            pct(st["numbers"]["stable"], st["numbers"]["total"]), st["numbers"]["max_spread"],
            cell(", ".join(odd) or "none")))
    return lines


def build_report(records, run_id, consistency=None):
    lines = ["# cascade evaluation", "", "Run: `%s`. Questions: %d. Pass: %d/%d." % (
        run_id, len(records), sum(1 for r in records if r.get("pass")), len(records)), ""]
    header = ["Group", "N", "Pass rate", "Grounded", "Level fit", "Persona fit", "Safety", "Clarity",
              "Median s", "p90 s"]
    sep = "|" + "|".join("---" for _ in header) + "|"
    head = "| " + " | ".join(header) + " |"

    checked, unchecked, sources = claim_totals(records)
    lines += ["## Factual accuracy", "",
              "Claims (labels, betas, impacts, verdicts) taken from the tool results are compared with "
              "`golden.json`. Labels and verdicts must match exactly; numbers within 0.005 absolute or 2%. "
              "Claims with no golden value are counted as unchecked and do not fail.", ""]
    lines += check_table(records, [("Claims match golden", "claims"), ("Expected label in tool trace", "label")])
    lines += ["", "Claim values checked: %d. Unchecked (no golden value): %d. Claims source: %s." % (
        checked, unchecked, ", ".join("%s %d" % kv for kv in sorted(sources.items())) or "none"), ""]
    lines += check_failures(records, ("claims", "label")) + [""]

    lines += ["## Faithfulness", "",
              "Whether the answer stays within what the tools and citations returned.", ""]
    lines += check_table(records, [("Numbers appear in tool output", "numbers"),
                                   ("Quoted spans are in a citation", "quotes"),
                                   ("source_urls exist in evidence", "sources")])
    lines += [""] + check_failures(records, ("numbers", "quotes", "sources")) + [""]

    lines += ["## Trajectory", "", "Which tools the agent called and with what arguments.", ""]
    lines += check_table(records, [("Required tools called", "must_call"),
                                   ("Tool arguments match the persona", "tool_args"),
                                   ("Tickers are the persona's holdings or alternatives", "tickers")])
    lines += [""] + check_failures(records, ("must_call", "tool_args", "tickers")) + [""]

    lines += ["## Consistency", ""] + consistency_lines(consistency) + [""]

    lines += ["## Answer content", ""]
    lines += check_table(records, [("Mentions required terms", "must_mention"), ("No forbidden wording", "must_not")])
    lines += [""] + check_failures(records, ("must_mention", "must_not")) + [""]

    lines += ["## Judge", "", "Judge scores are means on a 1-5 scale. Latency is end to end, in seconds.", ""]
    for persona in PERSONAS:
        recs = [r for r in records if r["persona"] == persona]
        lines += ["### %s" % persona.capitalize(), "", head, sep]
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

    lines += ["### Overall", "", head, sep, summary_row("all", records), ""]

    failed = [r for r in records if not r.get("pass")]
    lines += ["## Failed questions", ""]
    if not failed:
        lines.append("None.")
    for r in failed:
        lines.append("- **%s** (%s, %s): %s" % (r["id"], r["persona"], r["level"],
                                                cell("; ".join(r.get("reasons") or ["no reason recorded"]))))
    lines.append("")

    unverified = [(r["id"], r["checks"]["numbers"]["unverifiable"]) for r in records
                  if r.get("checks") and (r["checks"].get("numbers") or {}).get("unverifiable")]
    lines += ["## Numbers not verified (tool output was truncated)", ""]
    if not unverified:
        lines.append("None.")
    for qid, nums in unverified:
        lines.append("- **%s**: %s" % (qid, cell(", ".join(nums))))
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
    consistency = None
    cpath = os.path.join(os.path.dirname(os.path.abspath(path)), run_id + ".consistency.json")
    if os.path.exists(cpath):
        with open(cpath, encoding="utf-8") as f:
            consistency = json.load(f)
    md = build_report(records, run_id, consistency)
    out = os.path.join(os.path.dirname(os.path.abspath(path)), run_id + ".md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    bucket = os.environ.get("BUCKET", DEFAULT_BUCKET)
    import boto3
    boto3.client("s3", region_name=REGION).upload_file(out, bucket, "eval/%s/report.md" % run_id)
    print("wrote %s and s3://%s/eval/%s/report.md" % (out, bucket, run_id))


if __name__ == "__main__":
    main()
