"""Tests for the read-only Brent reproduction runner on SYNTHETIC raw files (no real market data).

Needs pandas, numpy and statsmodels (the same as compute/). Run:
    python -m pytest research/stats_repro -q      or      python -m unittest discover -s research/stats_repro
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

import brent_betas as bb
from readonly_store import LocalRawStore, ReadOnlyViolation

TRUE_BETAS = {"RY.TO": 0.0, "CNQ.TO": 0.45, "ATD.TO": -0.08, "CNR.TO": 0.0, "XIU.TO": 0.05, "XOM": 0.35,
              "VFV.TO": -0.02, "CP.TO": -0.02}


def write_raw(root, include_cp=False):
    """A tiny raw/ tree in the exact layout and columns load_raw reads. Known daily betas to Brent."""
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2021-11-12", "2026-11-13")
    brent_ret = rng.normal(0, 0.02, len(dates))
    brent = 80 * np.exp(np.cumsum(brent_ret))
    def prices(tickers):
        rows = []
        for t in tickers:
            r = TRUE_BETAS[t] * brent_ret + rng.normal(0, 0.004, len(dates))
            px = 50 * np.exp(np.cumsum(r))
            cur = "USD" if t == "XOM" else "CAD"
            rows += [(d.date().isoformat(), t, p, p, p, p, p, 1000, cur) for d, p in zip(dates, px)]
        return pd.DataFrame(rows, columns=["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "currency"])
    raw = Path(root) / "raw"
    (raw / "starter").mkdir(parents=True)
    (raw / "prices" / "snapshot=2026-11-14").mkdir(parents=True)
    (raw / "fred" / "snapshot=2026-11-14").mkdir(parents=True)
    prices(["XIU.TO", "XOM", "RY.TO", "CNQ.TO", "ATD.TO", "CNR.TO"]).to_csv(raw / "starter/prices_daily.csv", index=False)
    # The real extra snapshot always has rows; an EMPTY extra file makes build_weekly fail (object dtype).
    prices(["VFV.TO"] + (["CP.TO"] if include_cp else [])).to_csv(raw / "prices/snapshot=2026-11-14/prices_daily_extra.csv", index=False)
    pd.DataFrame({"date": dates.date, "usdcad": 1.35, "cadusd": 1 / 1.35}).to_csv(raw / "starter/fx_usdcad_daily.csv", index=False)
    macro = [(d.date(), sid, 3.0 + 0.01 * i % 1, "pct", "D", sid, "synthetic")
             for i, d in enumerate(dates) for sid in ("DGS10", "DGS2", "BD.CDN.10YR.DQ.YLD", "BD.CDN.2YR.DQ.YLD")]
    pd.DataFrame(macro, columns=["date", "series_id", "value", "unit", "frequency", "label", "source"]).to_csv(
        raw / "starter/macro_rates.csv", index=False)
    pd.DataFrame({"observation_date": dates.date, "DCOILBRENTEU": brent.round(4)}).to_csv(
        raw / "fred/snapshot=2026-11-14/DCOILBRENTEU.csv", index=False)
    pd.DataFrame({"observation_date": dates.date, "T10YIE": 2.3}).to_csv(raw / "fred/snapshot=2026-11-14/T10YIE.csv", index=False)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_recovers_known_betas_and_labels_them_computed(self):
        write_raw(self.tmp)
        out = bb.run(LocalRawStore(self.tmp), "synthetic")
        for t in bb.TARGETS:
            r = out["results"][t]
            self.assertEqual(r["status"], "computed_now")
            self.assertAlmostEqual(r["computed"]["beta_simple"], TRUE_BETAS[t], delta=0.04, msg=t)
            self.assertGreater(r["computed"]["n_weeks"], 200)
            self.assertEqual(r["method"]["standard_errors"], "Newey-West HAC, 4 lags")
            self.assertEqual(r["method"]["market_control"], "XIU.TO")
        self.assertTrue(out["results"]["CNQ.TO"]["significance"]["p_lt_0_05"])
        self.assertEqual(out["code_revision"]["compute_stats_py_sha256"].__len__(), 64)

    def test_every_input_is_hashed(self):
        write_raw(self.tmp)
        out = bb.run(LocalRawStore(self.tmp), "synthetic")
        self.assertEqual(len(out["inputs_read"]), 6)
        self.assertTrue(all(len(v["sha256"]) == 64 and v["bytes"] > 0 for v in out["inputs_read"].values()))

    def test_legacy_is_a_comparison_never_the_result(self):
        write_raw(self.tmp)
        out = bb.run(LocalRawStore(self.tmp), "synthetic")
        ry = out["results"]["RY.TO"]
        self.assertEqual(ry["legacy_comparison"]["legacy"]["beta_simple"], -0.020245)  # parsed from the notebook
        self.assertNotEqual(ry["computed"]["beta_simple"], -0.020245)                   # synthetic data differs
        self.assertIn("older code", ry["legacy_comparison"]["source"])

    def test_writes_are_impossible_and_module_is_restored(self):
        from compute import stats
        before = (stats.write_outputs, stats._s3_client, list(stats.UNIVERSE))
        write_raw(self.tmp)
        store = LocalRawStore(self.tmp)
        with self.assertRaises(ReadOnlyViolation):
            store.put_object(Bucket="b", Key="processed/x", Body=b"")
        with self.assertRaises(ReadOnlyViolation):
            store.delete_object(Bucket="b", Key="raw/starter/prices_daily.csv")
        bb.run(store, "synthetic", candidate="CP.TO")
        self.assertEqual((stats.write_outputs, stats._s3_client, list(stats.UNIVERSE)), before)
        with self.assertRaises(ReadOnlyViolation):
            bb._blocked()

    def test_missing_files_are_named(self):
        with self.assertRaisesRegex(FileNotFoundError, "raw/starter/prices_daily.csv"):
            LocalRawStore(self.tmp)  # no raw/ folder at all: lists every required key
        write_raw(self.tmp)
        (self.tmp / "raw/starter/fx_usdcad_daily.csv").unlink()
        with self.assertRaisesRegex(FileNotFoundError, "fx_usdcad_daily.csv"):
            bb.run(LocalRawStore(self.tmp), "synthetic")

    def test_candidate_ticker_is_estimated_with_a_universe_note(self):
        write_raw(self.tmp, include_cp=True)
        out = bb.run(LocalRawStore(self.tmp), "synthetic", candidate="CP.TO")
        cp = out["results"]["CP.TO"]
        self.assertEqual(cp["status"], "computed_now")
        self.assertAlmostEqual(cp["computed"]["beta_simple"], TRUE_BETAS["CP.TO"], delta=0.04)
        self.assertNotIn("legacy_comparison", cp)
        self.assertIn("q_simple values are Benjamini-Hochberg over 36", out["universe_note"])

    def test_candidate_without_price_rows_is_not_estimated(self):
        write_raw(self.tmp, include_cp=False)
        out = bb.run(LocalRawStore(self.tmp), "synthetic", candidate="CP.TO")
        self.assertEqual(out["results"]["CP.TO"]["status"], "not_estimated")

    def test_output_is_strict_json(self):
        write_raw(self.tmp)
        json.dumps(bb.run(LocalRawStore(self.tmp), "synthetic"), allow_nan=False, default=str)


if __name__ == "__main__":
    unittest.main()
