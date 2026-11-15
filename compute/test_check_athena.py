"""Tests for compute/check_athena.py. Synthetic data only; no AWS calls."""
import re

import numpy as np

from compute import check_athena as ca
from compute import stats
from compute.test_stats import make_data


def test_sql_file_has_the_three_statements_and_the_same_tickers():
    sql = ca.load_statements()
    assert set(sql) == {"create_weekly_returns", "recompute_beta_simple", "stored_beta_simple"}
    assert "regr_slope(ret_cad, brent_ret)" in sql["recompute_beta_simple"]
    for name in ("recompute_beta_simple", "stored_beta_simple"):
        listed = re.search(r"(?:subject_or_ticker|ticker) IN \(([^)]*)\)", sql[name]).group(1)
        assert tuple(t.strip().strip("'") for t in listed.split(",")) == ca.TICKERS
    assert len(ca.TICKERS) == 5
    assert "cascade-s3-bucket/processed/weekly_returns/" in sql["create_weekly_returns"]


def test_compare_within_tolerance_passes():
    stored = {t: 0.5 for t in ca.TICKERS}
    recomputed = {t: 0.5 + ca.TOLERANCE for t in ca.TICKERS}
    assert ca.compare_betas(recomputed, stored)["pass"]


def test_compare_outside_tolerance_fails_that_ticker():
    stored = {t: 0.5 for t in ca.TICKERS}
    recomputed = dict(stored, TLT=0.5 + 0.0021)
    res = ca.compare_betas(recomputed, stored)
    assert not res["pass"]
    assert [r["ticker"] for r in res["rows"] if not r["ok"]] == ["TLT"]


def test_compare_missing_or_null_fails():
    stored = {t: 0.5 for t in ca.TICKERS}
    recomputed = {t: 0.5 for t in ca.TICKERS if t != "QQQ"}
    res = ca.compare_betas(recomputed, stored)
    assert not res["pass"] and [r["ticker"] for r in res["rows"] if not r["ok"]] == ["QQQ"]
    assert not ca.compare_betas(dict(stored, XOM=None), stored)["pass"]


def test_betas_by_ticker_parses_athena_text():
    rows = [{"ticker": "XOM", "beta_simple": "0.81"}, {"ticker": "TLT", "beta_simple": None}]
    assert ca.betas_by_ticker(rows, "beta_simple") == {"XOM": 0.81, "TLT": None}


def test_regr_slope_on_stats_weekly_returns_matches_beta_simple():
    data = make_data()
    table = stats.weekly_returns_table(data, stats.build_subjects(data))
    assert list(table.columns) == ["week", "subject_or_ticker", "ret_cad", "brent_ret"]
    sens = stats.sensitivities(data).set_index("ticker")["beta_simple"]
    slopes = {}
    for t in ca.TICKERS:  # what Athena's regr_slope(ret_cad, brent_ret) computes per ticker
        g = table[table["subject_or_ticker"] == t].dropna(subset=["ret_cad", "brent_ret"])
        if len(g):
            slopes[t] = float(np.polyfit(g["brent_ret"], g["ret_cad"], 1)[0])
    assert len(slopes) == 5
    res = ca.compare_betas(slopes, {t: float(sens[t]) for t in slopes})
    assert res["pass"], res["rows"]
