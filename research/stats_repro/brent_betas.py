"""Read-only reproduction of the Brent regressions with the CURRENT compute/stats.py.

    # local mirror of the bucket's raw/ folder:
    python research/stats_repro/brent_betas.py --raw-dir /path/to/mirror --out results/run.json
    # inside SageMaker, reading S3 without any write permission being used:
    python research/stats_repro/brent_betas.py --s3-read-only --bucket cascade-s3-bucket --out results/run.json
    # optional extra ticker not in the contract universe (needs its price rows in the same raw files):
    ... --candidate-ticker CP.TO

It imports compute.stats unchanged, calls load_raw -> build_weekly -> sensitivities, and NEVER calls
write_outputs or any S3 write (both are disabled in-process; the stores are read-only). Results are
labelled as computed now, with input hashes and the code revision. Legacy notebook values are shown
only as a comparison and are never copied into the computed fields.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from readonly_store import LocalRawStore, ReadOnlyS3, ReadOnlyViolation  # noqa: E402

TARGETS = ("RY.TO", "CNQ.TO", "ATD.TO", "CNR.TO")
NOTEBOOK = REPO / "compute" / "run_stats.ipynb"


def _blocked(*a, **k):
    raise ReadOnlyViolation("write_outputs is disabled in the read-only reproduction runner")


def code_revision():
    def git(*args):
        try:
            return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    stats_py = REPO / "compute" / "stats.py"
    return {"git_commit": git("rev-parse", "HEAD"),
            "compute_stats_py_sha256": hashlib.sha256(stats_py.read_bytes()).hexdigest(),
            "compute_stats_py_uncommitted_changes": bool(git("status", "--porcelain", "--", "compute/stats.py")),
            "python": platform.python_version()}


def legacy_from_notebook(tickers, path=NOTEBOOK):
    """Parse the saved (legacy) sensitivities display in run_stats.ipynb cell 9. Visible columns only."""
    nb = json.loads(Path(path).read_text())
    cell = next(c for c in nb["cells"] if "".join(c.get("source", [])).strip().startswith("sens = stats.sensitivities"))
    text = "".join("".join(o.get("data", {}).get("text/plain", [])) for o in cell.get("outputs", []))
    rows, names = {}, {}
    for block in [b for b in text.split("\n\n") if b.strip()]:
        lines = block.split("\n")
        header = [h for h in lines[0].replace("\\", " ").split()]
        for line in lines[1:]:
            parts = line.replace("\\", " ").split()
            if not parts or not parts[0].isdigit():
                continue
            values = parts[1:]
            if len(values) != len(header):
                continue
            row = rows.setdefault(parts[0], {})
            for h, v in zip(header, values):
                if h != "...":
                    row[h] = v
            if "ticker" in row:
                names[row["ticker"]] = parts[0]
    out = {}
    for t in tickers:
        row = rows.get(names.get(t), {})
        out[t] = {k: (float(v) if re.fullmatch(r"-?[\d.]+(e[-+]\d+)?", v) else v) for k, v in row.items() if k != "ticker"}
    return out


def significance(p, lo, hi):
    ok = p is not None and not (isinstance(p, float) and math.isnan(p))
    return {"p_lt_0_05": bool(ok and p < 0.05),
            "ci95_excludes_zero": bool(ok and (lo > 0 or hi < 0)),
            "verdict": "significant at 5%" if ok and p < 0.05 else "not significant at 5%" if ok else "not estimated"}


def run(store, bucket, tickers=TARGETS, candidate=None):
    """Guards are applied in-process and always restored, so compute.stats is left exactly as imported."""
    from compute import stats
    saved = (stats.write_outputs, stats._s3_client, stats.UNIVERSE)
    stats.write_outputs = _blocked     # the source file is never modified
    stats._s3_client = _blocked
    try:
        return _run(stats, store, bucket, tickers, candidate)
    finally:
        stats.write_outputs, stats._s3_client, stats.UNIVERSE = saved


def _run(stats, store, bucket, tickers, candidate):
    universe_note = None
    if candidate:
        if candidate in stats.UNIVERSE:
            raise ValueError(f"{candidate} is already in the universe")
        stats.UNIVERSE = stats.UNIVERSE + [candidate]  # in-memory only, for this process
        universe_note = (f"{candidate} appended to the universe in memory for this run only. q_simple values are "
                         f"Benjamini-Hochberg over {len(stats.UNIVERSE)} tickers and differ from the contract run.")
    raw = stats.load_raw(bucket, store)
    data = stats.build_weekly(raw)
    sens = stats.sensitivities(data).set_index("ticker")
    legacy = legacy_from_notebook(tickers)
    results = {}
    for t in list(tickers) + ([candidate] if candidate else []):
        if t not in sens.index:
            results[t] = {"status": "not_estimated", "reason": "ticker absent or skipped by build_weekly (see warnings)"}
            continue
        r = sens.loc[t]
        f = lambda c: None if r[c] is None or (isinstance(r[c], float) and math.isnan(r[c])) else float(r[c])  # noqa: E731
        y = data.ret_cad[t].dropna()
        weeks = y.index.intersection(data.brent.dropna().index)
        computed = {k: f(k) for k in ("beta_simple", "lo_simple", "hi_simple", "p_simple", "beta_mkt", "lo_mkt",
                                       "hi_mkt", "p_mkt", "beta_ex2022", "lo_ex2022", "hi_ex2022", "p_ex2022",
                                       "q_simple")}
        computed["n_weeks"] = int(r["n_weeks"])
        rec = {
            "status": "computed_now",
            "computed": computed,
            "significance": significance(computed["p_simple"], computed["lo_simple"], computed["hi_simple"]),
            "sample": {"first_week": str(weeks.min().date()), "last_week": str(weeks.max().date()),
                       "weeks_with_return_and_brent": int(len(weeks)), "sample_start_rule": stats.SAMPLE_START},
            "method": {"model": "OLS of weekly ticker return on weekly Brent return, with constant",
                       "standard_errors": f"Newey-West HAC, {stats.HAC_LAGS} lags", "ci": "beta +/- 1.96 * se",
                       "market_control": r["market_ticker"],
                       "returns": "weekly (W-FRI, last available adj_close) log returns, in CAD "
                                  "(USD tickers: + weekly log change of USD/CAD)",
                       "factor": "weekly log return of Brent (FRED DCOILBRENTEU, USD/bbl)",
                       "units": "beta = log-return of the ticker per 1.0 log-return of Brent (about % per %)",
                       "currency": str(data.currency[t])},
        }
        old = legacy.get(t) or {}
        if old.get("beta_simple") is not None:
            rec["legacy_comparison"] = {
                "source": "saved display in compute/run_stats.ipynb cell 9 (older code, unknown run date, display precision)",
                "legacy": {k: old.get(k) for k in ("beta_simple", "lo_simple", "hi_simple", "p_simple", "n_weeks")},
                "beta_difference": None if computed["beta_simple"] is None else computed["beta_simple"] - old["beta_simple"],
                "same_sign": None if computed["beta_simple"] is None else (computed["beta_simple"] >= 0) == (old["beta_simple"] >= 0),
                "same_significance_at_5pct": (computed["p_simple"] is not None and old.get("p_simple") is not None
                                              and (computed["p_simple"] < 0.05) == (old["p_simple"] < 0.05)),
            }
        results[t] = rec
    return {
        "kind": "read_only_reproduction", "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "code_revision": code_revision(), "inputs_read": store.reads, "bucket": bucket,
        "universe_note": universe_note, "results": results,
        "libraries": {m: __import__(m).__version__ for m in ("pandas", "numpy", "statsmodels")},
        "not_done": ["write_outputs not called", "no S3 writes", "q_simple depends on the full universe"],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--raw-dir", type=Path, help="local folder containing raw/ like the bucket")
    src.add_argument("--s3-read-only", action="store_true", help="read s3://BUCKET/raw/ through a read-only wrapper")
    p.add_argument("--bucket", default="cascade-s3-bucket")
    p.add_argument("--tickers", nargs="+", default=list(TARGETS))
    p.add_argument("--candidate-ticker", help="add one non-universe ticker in memory, e.g. CP.TO")
    p.add_argument("--out", type=Path, help="new JSON file under research/stats_repro/results/ (never overwritten)")
    a = p.parse_args(argv)
    if a.s3_read_only:
        import boto3
        store = ReadOnlyS3(boto3.client("s3"))
    else:
        store = LocalRawStore(a.raw_dir)
    result = run(store, a.bucket, a.tickers, a.candidate_ticker)
    text = json.dumps(result, indent=2, default=str, allow_nan=False) + "\n"
    if a.out:
        target = (HERE / a.out).resolve() if not a.out.is_absolute() else a.out.resolve()
        if not target.is_relative_to(HERE / "results"):
            raise SystemExit("--out must be inside research/stats_repro/results/")
        target.parent.mkdir(exist_ok=True)
        with target.open("x") as fh:
            fh.write(text)
        print("wrote", target)
    else:
        print(text)


if __name__ == "__main__":
    main()
