"""Unit tests for compute/stats.py using synthetic data with known betas."""

import io

import numpy as np
import pandas as pd
import pytest

from compute import stats

N_WEEKS = 260
WEEKS = pd.date_range("2021-11-19", periods=N_WEEKS, freq="W-FRI")


def _rng():
    return np.random.default_rng(42)


US_TICKERS = ("XOM", "TLT", "QQQ", "SPY", "NVDA", "GLD", "AGG", "ESGV")


def make_data(extra=None, tickers=None):
    """Synthetic WeeklyData: known betas for each ticker, small noise."""
    tickers = tickers or stats.CORE_TICKERS
    rng = _rng()
    brent = pd.Series(rng.normal(0, 0.04, N_WEEKS), index=WEEKS, name="brent")
    market = pd.Series(0.3 * brent.to_numpy() + rng.normal(0, 0.02, N_WEEKS), index=WEEKS)
    ret = {}
    for t in tickers:
        ret[t] = pd.Series(rng.normal(0, 0.005, N_WEEKS), index=WEEKS)
    ret["XOM"] += 0.8 * brent
    ret["TLT"] += -0.1 * brent
    ret["SPY"] = market + ret["SPY"]
    ret["XIU.TO"] = market + ret["XIU.TO"]
    ret["ENB.TO"] += 0.5 * brent + 1.0 * market
    for t, v in (extra or {}).items():
        ret[t] = v
    ret_cad = pd.DataFrame(ret)[tickers]
    dy = pd.DataFrame({
        "us10y": 0.5 * brent + rng.normal(0, 0.02, N_WEEKS),
        "us2y": rng.normal(0, 0.02, N_WEEKS),
        "ca10y": 0.4 * brent + rng.normal(0, 0.02, N_WEEKS),
        "ca2y": rng.normal(0, 0.02, N_WEEKS),
        "breakeven": 0.2 * brent + rng.normal(0, 0.02, N_WEEKS),
    }, index=WEEKS)
    currency = pd.Series({t: ("USD" if t in US_TICKERS else "CAD") for t in tickers})
    return stats.WeeklyData(ret_local=ret_cad.copy(), ret_cad=ret_cad, brent=brent,
                            usdcad=pd.Series(rng.normal(0, 0.01, N_WEEKS), index=WEEKS),
                            dy=dy, currency=currency)


def test_regress_recovers_beta():
    rng = _rng()
    x = pd.Series(rng.normal(0, 1, 400))
    y = 0.5 * x + rng.normal(0, 0.5, 400)
    r = stats.regress(y, x)
    assert abs(r["beta"] - 0.5) < 0.05
    assert r["lo"] < r["beta"] < r["hi"]
    assert r["p"] < 0.05
    assert r["n"] == 400


def test_regress_too_few_rows_is_nan():
    r = stats.regress(pd.Series([1.0, 2.0, 3.0]), pd.Series([1.0, 2.0, 4.0]))
    assert np.isnan(r["beta"]) and r["n"] == 3


def test_regress_with_control_removes_market_effect():
    rng = _rng()
    m = pd.Series(rng.normal(0, 1, 500))
    x = 0.6 * m + rng.normal(0, 0.8, 500)          # x correlated with market
    y = 0.5 * x + 1.0 * m + rng.normal(0, 0.3, 500)
    simple = stats.regress(y, x)["beta"]
    controlled = stats.regress_with_control(y, x, m)["beta"]
    assert abs(controlled - 0.5) < 0.05
    assert abs(simple - 0.5) > 0.2                  # omitted-variable bias without control


def test_pick_latest_snapshot():
    names = ["raw/fred/snapshot=2026-10-01/", "raw/fred/snapshot=2026-11-12/", "raw/fred/snapshot=2026-09-30/"]
    assert stats.pick_latest_snapshot(names) == "raw/fred/snapshot=2026-11-12/"
    assert stats.pick_latest_snapshot(["raw/fred/other/"]) is None


def test_parse_fred_handles_dot_and_header_names():
    df = pd.DataFrame({"observation_date": ["2024-01-01", "2024-01-02", "2024-01-03"],
                       "DCOILBRENTEU": ["70.0", ".", "71.0"]})
    s = stats.parse_fred(df)
    assert s.isna().tolist() == [False, True, False]
    df2 = pd.DataFrame({"DATE": ["2024-01-01"], "T10YIE": ["2.1"]})
    assert stats.parse_fred(df2).iloc[0] == 2.1


def _raw_frames(brent_values, tickers=None, short=None):
    """Raw CSV-like frames. `short` maps ticker -> number of days of history to keep."""
    tickers = tickers or stats.CORE_TICKERS
    short = short or {}
    days = pd.bdate_range("2021-11-12", periods=len(brent_values))
    prices = []
    for t in tickers:
        cur = "USD" if t in US_TICKERS else "CAD"
        d = days[: short.get(t, len(days))]
        prices.append(pd.DataFrame({"date": d, "ticker": t, "adj_close": 100.0 * 1.001 ** np.arange(len(d)),
                                    "currency": cur}))
    prices = pd.concat(prices)
    starter = prices[~prices["ticker"].isin(["VFV.TO", "XSP.TO", "XESG.TO"])]
    extra = prices[prices["ticker"].isin(["VFV.TO", "XSP.TO", "XESG.TO"])]
    fx = pd.DataFrame({"date": days, "usdcad": 1.25 * 1.002 ** np.arange(len(days))})
    macro = pd.concat([
        pd.DataFrame({"date": days, "series_id": sid, "value": 2.0 + 0.01 * np.arange(len(days))})
        for sid in ("DGS10", "DGS2", "BD.CDN.10YR.DQ.YLD", "BD.CDN.2YR.DQ.YLD")])
    brent = pd.DataFrame({"observation_date": days, "DCOILBRENTEU": [str(v) for v in brent_values]})
    t10yie = pd.DataFrame({"observation_date": days, "T10YIE": ["2.0"] * len(days)})
    return {"prices_starter": starter, "prices_extra": extra, "fx": fx, "macro": macro,
            "brent": brent, "t10yie": t10yie}


def test_build_weekly_conversion_and_missing_brent():
    n = 40
    brent = [80.0 * 1.001 ** i for i in range(n)]
    brent[7] = "."   # a missing day does not remove its week (other days remain)
    for i in range(11, 16):
        brent[i] = "."  # Mon-Fri 2021-11-29..12-03 missing -> week of 12-03 has no Brent value
    raw = _raw_frames(brent)
    d = stats.build_weekly(raw, min_returns=1)
    assert list(d.ret_cad.columns) == stats.CORE_TICKERS
    # USD ticker = local return + usdcad change, CAD ticker = local return
    w = d.ret_cad.index[3]
    assert d.ret_cad.loc[w, "XOM"] == pytest.approx(d.ret_local.loc[w, "XOM"] + d.usdcad.loc[w])
    assert d.ret_cad.loc[w, "RY.TO"] == pytest.approx(d.ret_local.loc[w, "RY.TO"])
    # weekly log return of a 5-day, 0.1%/day series
    assert d.ret_local.loc[w, "RY.TO"] == pytest.approx(5 * np.log(1.001))
    assert d.brent.notna().all()
    assert pd.Timestamp("2021-12-03") not in d.brent.index   # week without Brent is dropped
    assert pd.Timestamp("2021-12-10") not in d.brent.index   # its return needs the missing level
    # yields are changes in percentage points (0.01/day -> 0.05/week)
    assert d.dy.loc[w, "us10y"] == pytest.approx(0.05)
    assert (d.ret_cad.index >= pd.Timestamp(stats.SAMPLE_START)).all()


def test_sensitivities_known_betas():
    data = make_data()
    s = stats.sensitivities(data).set_index("ticker")
    assert list(stats.sensitivities(data).columns) == stats.SENSITIVITY_COLUMNS
    assert len(s) == 14
    assert abs(s.loc["XOM", "beta_simple"] - 0.8) < 0.05
    assert s.loc["XOM", "p_simple"] < 0.05
    assert s.loc["TLT", "beta_simple"] < 0
    assert s.loc["XOM", "exxon_equiv"] == pytest.approx(1.0)
    assert abs(s.loc["TLT", "exxon_equiv"] - (-0.1 / 0.8)) < 0.1
    assert s.loc["XOM", "market_ticker"] == "SPY"
    assert s.loc["ENB.TO", "market_ticker"] == "XIU.TO"
    assert abs(s.loc["ENB.TO", "beta_mkt"] - 0.5) < 0.1
    assert s.loc["ENB.TO", "r2_incremental"] > 0
    assert (s["n_weeks"] == N_WEEKS).all()


def test_market_etfs_copy_simple_values():
    s = stats.sensitivities(make_data()).set_index("ticker")
    for t in ["XIU.TO", "XESG.TO", "SPY", "VFV.TO", "XSP.TO"]:
        assert s.loc[t, "market_ticker"] == "none"
        assert s.loc[t, "beta_mkt"] == s.loc[t, "beta_simple"]
        assert s.loc[t, "p_mkt"] == s.loc[t, "p_simple"]


def test_ex2022_excludes_2022_weeks():
    data = make_data()
    in_2022 = data.brent.index.year == 2022
    y = data.ret_cad["ATD.TO"].copy()
    y[in_2022] = y[in_2022] + 5.0 * data.brent[in_2022]   # beta 5 only in 2022
    data.ret_cad["ATD.TO"] = y
    s = stats.sensitivities(data).set_index("ticker")
    assert abs(s.loc["ATD.TO", "beta_ex2022"]) < 0.3
    assert s.loc["ATD.TO", "beta_simple"] > 0.4   # 2022 inflates the full-sample beta


def test_asymmetry_up_and_down_betas():
    data = make_data()
    x = data.brent
    y = pd.Series(np.where(x > 0, 1.0 * x, 0.2 * x), index=x.index)
    data.ret_cad["RY.TO"] = y
    s = stats.sensitivities(data).set_index("ticker")
    assert s.loc["RY.TO", "beta_up"] == pytest.approx(1.0, abs=1e-6)
    assert s.loc["RY.TO", "beta_down"] == pytest.approx(0.2, abs=1e-6)


def test_out_of_sample_hit_rate_and_count():
    rng = _rng()
    x = pd.Series(rng.normal(0, 0.04, N_WEEKS), index=WEEKS)
    y = 0.5 * x + rng.normal(0, 0.002, N_WEEKS)
    hit, n = stats.out_of_sample(y, x)
    n_test = int((WEEKS >= pd.Timestamp("2025-01-01")).sum())
    assert n == int(np.ceil(0.1 * n_test))
    assert hit == 1.0
    # wrong-sign relationship out of sample gives hit rate 0
    y2 = y.copy()
    y2[WEEKS >= pd.Timestamp("2025-01-01")] *= -1
    assert stats.out_of_sample(y2, x)[0] == 0.0


def test_out_of_sample_without_test_weeks():
    x = pd.Series(np.arange(50, dtype=float), index=pd.date_range("2022-01-07", periods=50, freq="W-FRI"))
    hit, n = stats.out_of_sample(2 * x, x)
    assert np.isnan(hit) and n == 0


def test_rolling_beta_constant_relationship():
    data = make_data()
    data.ret_cad["RY.TO"] = 0.5 * data.brent
    r = stats.rolling_betas(data)
    ry = r[r["ticker"] == "RY.TO"]
    assert len(ry) == N_WEEKS - stats.ROLLING_WINDOW + 1
    assert ry["beta_52w"].between(0.49, 0.51).all()
    assert list(r.columns) == ["ticker", "week", "beta_52w", "universe"]
    assert (r["universe"] == "core").all()


def test_links_chain_and_duration():
    rng = _rng()
    data = make_data()
    # build an exact chain: TLT = -4 * d(us10y)
    data.ret_cad["TLT"] = -4.0 * data.dy["us10y"] + rng.normal(0, 0.001, N_WEEKS)
    sens = stats.sensitivities(data)
    lk = stats.links(data)
    assert list(lk.columns) == ["link_id", "from_node", "to_node", "beta", "lo", "hi", "p", "unit"]
    assert len(lk) == 10
    ids = lk.set_index("link_id")
    assert abs(ids.loc["oil>us10y", "beta"] - 0.5) < 0.1
    assert abs(ids.loc["us10y>TLT", "beta"] + 4.0) < 0.1
    assert ids.loc["us10y>TLT", "unit"] == "log per pp"

    chain = stats.chain_reconciliation(lk, sens).set_index("ticker")
    assert set(chain.index) == {"TLT", "XBB.TO", "ZST.TO", "VFV.TO", "QQQ", "SHOP.TO"}
    assert chain.loc["TLT", "beta_chain"] == pytest.approx(
        ids.loc["oil>us10y", "beta"] * ids.loc["us10y>TLT", "beta"])
    assert chain.loc["TLT", "share_explained"] == pytest.approx(
        chain.loc["TLT", "beta_chain"] / chain.loc["TLT", "beta_direct"])

    dur = stats.duration_check(lk, sens).set_index("ticker")
    assert list(dur.index) == ["TLT", "XBB.TO", "ZST.TO"]
    bp = ids.loc["oil>us10y", "beta"] * np.log(1.10) * 100
    assert dur.loc["TLT", "yield_move_per_10pct_oil_bp"] == pytest.approx(bp)
    assert dur.loc["TLT", "implied_move_pct"] == pytest.approx(-14.63 * bp / 100)
    assert dur.loc["TLT", "measured_move_pct"] == pytest.approx(
        sens.set_index("ticker").loc["TLT", "beta_simple"] * np.log(1.10) * 100)


def test_chain_share_is_nan_for_zero_direct_beta():
    lk = pd.DataFrame({"link_id": [i for c in stats.CHAINS.values() for i in c[1]]}).drop_duplicates()
    lk["beta"] = 1.0
    sens = pd.DataFrame({"ticker": stats.CORE_TICKERS, "beta_simple": 0.0})
    out = stats.chain_reconciliation(lk, sens)
    assert out["share_explained"].isna().all()


def test_shock_impact_formula():
    assert stats.shock_impact_pct(1.0, 30) == pytest.approx(30.0)
    assert stats.shock_impact_pct(0.0, -30) == pytest.approx(0.0)
    assert stats.shock_impact_pct(2.0, 15) == pytest.approx(100 * (1.15 ** 2 - 1))
    assert stats.shock_impact_pct(-1.0, -30) == pytest.approx(100 * (1 / 0.7 - 1))


def test_persona_holdings_weights_sum_to_one():
    h = stats.persona_holdings()
    assert h.groupby("persona")["weight"].sum().tolist() == pytest.approx([1.0, 1.0, 1.0])
    assert set(h["persona"]) == {"robert", "amira", "mateo"}


def _sens_with_betas(betas):
    return pd.DataFrame({"ticker": stats.CORE_TICKERS,
                         "beta_simple": [betas.get(t, 0.0) for t in stats.CORE_TICKERS],
                         "lo_simple": [betas.get(t, 0.0) - 0.1 for t in stats.CORE_TICKERS],
                         "hi_simple": [betas.get(t, 0.0) + 0.1 for t in stats.CORE_TICKERS]})


def test_portfolio_exposure_per_holding():
    sens = _sens_with_betas({"TLT": -0.2, "XBB.TO": -0.1, "ENB.TO": 0.5, "RY.TO": 0.2})
    exp = stats.portfolio_exposure(stats.persona_holdings(), sens)
    assert list(exp.columns) == ["persona", "ticker", "weight", "beta", "lo", "hi", "contribution"]
    r = exp[exp["persona"] == "robert"]
    assert r["contribution"].sum() == pytest.approx(0.30 * -0.2 + 0.40 * -0.1 + 0.15 * 0.5 + 0.15 * 0.2)
    assert (exp["lo"] < exp["beta"]).all() and (exp["hi"] > exp["beta"]).all()


def test_scenarios_shape_and_ordering():
    sens = _sens_with_betas({"XOM": 1.0, "TLT": -0.5})
    pbeta = pd.DataFrame({"persona": ["robert", "amira", "mateo"], "beta": [0.5, 1.0, -0.2],
                          "lo": [0.4, 0.9, -0.3], "hi": [0.6, 1.1, -0.1]})
    sc = stats.scenarios(sens, pbeta)
    assert list(sc.columns) == ["subject", "subject_type", "shock_pct", "impact_pct", "lo_pct", "hi_pct"]
    assert len(sc) == (3 + 14) * 4
    assert set(sc["subject_type"]) == {"persona", "ticker"}
    xom30 = sc[(sc["subject"] == "XOM") & (sc["shock_pct"] == 30)].iloc[0]
    assert xom30["impact_pct"] == pytest.approx(30.0)
    assert (sc["lo_pct"] <= sc["hi_pct"]).all()
    xom_m30 = sc[(sc["subject"] == "XOM") & (sc["shock_pct"] == -30)].iloc[0]
    assert xom_m30["lo_pct"] <= xom_m30["impact_pct"] <= xom_m30["hi_pct"]
    amira30 = sc[(sc["subject"] == "amira") & (sc["shock_pct"] == 30)].iloc[0]
    assert amira30["subject_type"] == "persona"
    assert amira30["impact_pct"] == pytest.approx(30.0)   # persona beta 1.0 from portfolio_beta
    assert amira30["lo_pct"] == pytest.approx(float(stats.shock_impact_pct(0.9, 30)))
    assert amira30["hi_pct"] == pytest.approx(float(stats.shock_impact_pct(1.1, 30)))


def test_alternatives_swap_math():
    betas = {"TLT": -0.3, "ZST.TO": 0.0, "XBB.TO": -0.2, "QQQ": 1.0, "XIU.TO": 0.4,
             "ENB.TO": 0.5, "RY.TO": 0.2, "SHOP.TO": 1.5}
    sens = _sens_with_betas(betas)
    alt = stats.alternatives(stats.persona_holdings(), sens)
    assert list(alt.columns) == ["persona", "holding", "alternative", "beta_holding", "beta_alternative",
                                 "impact30_before_pct", "impact30_after_pct"]
    assert len(alt) == 5
    # amira QQQ->XIU.TO moves only 0.25 of weight
    a = alt[(alt["persona"] == "amira") & (alt["holding"] == "QQQ")].iloc[0]
    before = 0.5 * 1.0 + 0.25 * 1.5 + 0.25 * 0.4
    after = 0.25 * 1.0 + 0.25 * 1.5 + 0.50 * 0.4
    assert a["impact30_before_pct"] == pytest.approx(float(stats.shock_impact_pct(before, 30)))
    assert a["impact30_after_pct"] == pytest.approx(float(stats.shock_impact_pct(after, 30)))
    # robert TLT->ZST.TO moves the whole 0.30
    r = alt[(alt["persona"] == "robert") & (alt["holding"] == "TLT")].iloc[0]
    b = 0.30 * -0.3 + 0.40 * -0.2 + 0.15 * 0.5 + 0.15 * 0.2
    assert r["impact30_after_pct"] == pytest.approx(float(stats.shock_impact_pct(b - 0.30 * -0.3, 30)))


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.objects[(Bucket, Key)] = Body


def test_write_outputs_keys_and_parquet_roundtrip():
    data = make_data()
    sens = stats.sensitivities(data)
    holdings = stats.persona_holdings()
    exp = stats.portfolio_exposure(holdings, sens)
    pbeta = stats.portfolio_beta(data, holdings)
    tables = {"sensitivities": sens, "persona_holdings": holdings, "portfolio_exposure": exp,
              "portfolio_beta": pbeta}
    s3 = FakeS3()
    keys = stats.write_outputs(tables, "test-bucket", s3)
    assert keys == ["processed/sensitivities/part-0.parquet", "processed/persona_holdings/part-0.parquet",
                    "processed/portfolio_exposure/part-0.parquet", "processed/portfolio_beta/part-0.parquet",
                    "processed/_summary/summary.md"]
    back = pd.read_parquet(io.BytesIO(s3.objects[("test-bucket", "processed/sensitivities/part-0.parquet")]))
    assert len(back) == 14
    md = s3.objects[("test-bucket", "processed/_summary/summary.md")].decode()
    assert "| sensitivities | 14 |" in md
    assert "robert" in md and "amira" in md and "mateo" in md


def test_rolling_week_is_date_for_parquet():
    r = stats.rolling_betas(make_data())
    assert not isinstance(r["week"].iloc[0], pd.Timestamp)


# ---------------------------------------------------------------------------
# Universe, market control, short history
# ---------------------------------------------------------------------------

def test_universe_definition():
    assert len(stats.CORE_TICKERS) == 14
    assert len(stats.EXTRA_TICKERS) == 21
    assert stats.UNIVERSE == stats.CORE_TICKERS + stats.EXTRA_TICKERS
    assert len(set(stats.UNIVERSE)) == 35
    assert stats.EXTRA_TICKERS[-3:] == ["XRB.TO", "XLB.TO", "XEG.TO"]
    assert not {"BTC-USD", "ETH-USD"} & set(stats.UNIVERSE)


def test_market_control_for_new_tickers():
    f = stats.market_ticker_for
    for t in ["GLD", "AGG", "ESGV", "XRB.TO", "XLB.TO", "XEG.TO"]:
        assert f(t, "USD" if t in ("GLD", "AGG", "ESGV") else "CAD") == "none"
    assert f("NVDA", "USD") == "SPY"
    assert f("JPM", "USD") == "SPY"
    assert f("CNQ.TO", "CAD") == "XIU.TO"
    assert f("TD.TO", "CAD") == "XIU.TO"


def test_sensitivities_cover_universe_with_universe_column():
    data = make_data(tickers=stats.UNIVERSE)
    s = stats.sensitivities(data)
    assert list(s.columns) == stats.SENSITIVITY_COLUMNS
    assert len(s) == 35
    assert (s["universe"] == "core").sum() == 14 and (s["universe"] == "extra").sum() == 21
    s = s.set_index("ticker")
    assert s.loc["GLD", "market_ticker"] == "none"
    assert s.loc["GLD", "beta_mkt"] == s.loc["GLD", "beta_simple"]
    assert s.loc["NVDA", "market_ticker"] == "SPY"
    assert s.loc["CNQ.TO", "market_ticker"] == "XIU.TO"
    assert s.loc["XEG.TO", "market_ticker"] == "none"


def test_rolling_covers_universe():
    r = stats.rolling_betas(make_data(tickers=stats.UNIVERSE))
    assert r["ticker"].nunique() == 35
    assert set(r.loc[r["ticker"] == "NVDA", "universe"]) == {"extra"}


def test_new_links_and_chains_for_xlb_xrb():
    tickers = stats.CORE_TICKERS + ["XRB.TO", "XLB.TO"]
    data = make_data(tickers=tickers)
    sens = stats.sensitivities(data)
    lk = stats.links(data)
    assert {"ca10y>XLB.TO", "ca10y>XRB.TO"} <= set(lk["link_id"])
    ch = stats.chain_reconciliation(lk, sens).set_index("ticker")
    assert ch.loc["XLB.TO", "chain"] == "oil>ca10y>XLB.TO"
    assert ch.loc["XRB.TO", "chain"] == "oil>ca10y>XRB.TO"


def test_short_history_ticker_is_skipped_with_warning(capsys):
    n_days = 5 * 190                       # about 190 weeks of history
    brent = [80.0 * 1.001 ** i for i in range(n_days)]
    raw = _raw_frames(brent, tickers=stats.CORE_TICKERS, short={"XSP.TO": 5 * 60})
    btc = raw["prices_extra"].iloc[:50].assign(ticker="BTC-USD")
    raw["prices_extra"] = pd.concat([raw["prices_extra"], btc])
    d = stats.build_weekly(raw)
    out = capsys.readouterr().out
    assert "XSP.TO" not in d.ret_cad.columns
    assert "WARNING" in out and "XSP.TO" in out
    assert "XRB.TO" in out                 # extras with no rows are skipped with a warning too
    assert "RY.TO" in d.ret_cad.columns and "XOM" in d.ret_cad.columns
    assert "BTC-USD" not in d.ret_cad.columns
    # downstream steps still run with the ticker missing
    sens = stats.sensitivities(d)
    assert "XSP.TO" not in set(sens["ticker"])
    assert len(stats.links(d)) == 10


# ---------------------------------------------------------------------------
# Multiple testing and portfolio beta
# ---------------------------------------------------------------------------

def test_bh_adjust_known_vector():
    p = pd.Series([0.01, 0.04, 0.03, 0.005], index=list("abcd"))
    q = stats.bh_adjust(p)
    # sorted p: .005 .01 .03 .04 -> p*m/rank = .02 .02 .04 .04
    assert q.to_dict() == pytest.approx({"a": 0.02, "b": 0.04, "c": 0.04, "d": 0.02})
    assert (q >= p).all() and (q <= 1).all()


def test_bh_adjust_keeps_nan_and_does_not_count_it():
    p = pd.Series([0.01, np.nan, 0.04, 0.03, 0.005])
    q = stats.bh_adjust(p)
    assert np.isnan(q[1])
    assert q.drop(1).tolist() == pytest.approx([0.02, 0.04, 0.04, 0.02])


def test_q_simple_added_and_p_simple_unchanged():
    data = make_data(tickers=stats.UNIVERSE)
    s = stats.sensitivities(data)
    assert s["q_simple"].tolist() == pytest.approx(stats.bh_adjust(s["p_simple"]).tolist())
    assert (s["q_simple"] >= s["p_simple"] - 1e-12).all()
    assert s["p_simple"].tolist() == [stats.regress(data.ret_cad[t], data.brent)["p"] for t in s["ticker"]]


def test_portfolio_beta_is_weighted_sum_of_known_betas():
    rng = np.random.default_rng(7)   # independent of the seed used for brent in make_data
    data = make_data()
    x = data.brent
    data.ret_cad["XOM"] = 1.0 * x + rng.normal(0, 0.01, N_WEEKS)
    data.ret_cad["TLT"] = -0.5 * x + rng.normal(0, 0.01, N_WEEKS)
    holdings = pd.DataFrame({"persona": ["demo", "demo"], "ticker": ["XOM", "TLT"], "weight": [0.6, 0.4]})
    pb = stats.portfolio_beta(data, holdings)
    assert list(pb.columns) == ["persona", "beta", "lo", "hi", "p", "r2", "n_weeks"]
    r = pb.iloc[0]
    assert abs(r["beta"] - (0.6 * 1.0 + 0.4 * -0.5)) < 0.05
    assert r["lo"] < r["beta"] < r["hi"]
    assert r["p"] < 0.05
    assert r["n_weeks"] == N_WEEKS


def test_portfolio_beta_for_all_demo_personas():
    data = make_data()
    pb = stats.portfolio_beta(data, stats.persona_holdings())
    assert sorted(pb["persona"]) == ["amira", "mateo", "robert"]
    assert pb["beta"].notna().all()


def test_portfolio_beta_skips_persona_with_missing_ticker(capsys):
    data = make_data()
    data.ret_cad = data.ret_cad.drop(columns=["QQQ"])
    pb = stats.portfolio_beta(data, stats.persona_holdings())
    assert sorted(pb["persona"]) == ["mateo", "robert"]
    assert "WARNING" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# summary.md
# ---------------------------------------------------------------------------

def test_summary_lists_top10_by_abs_beta_with_q_below_010():
    n = 13
    sens = pd.DataFrame({
        "ticker": [f"T{i}" for i in range(n)],
        "beta_simple": [float(i + 1) * (-1 if i % 2 else 1) for i in range(n)],
        "lo_simple": 0.0, "hi_simple": 1.0,
        "q_simple": 0.01, "p_ex2022": 0.02, "oos_hit_rate": 0.75,
    })
    sens.loc[n - 1, "q_simple"] = 0.5            # largest |beta| but not significant: excluded
    pbeta = pd.DataFrame({"persona": ["robert"], "beta": [0.1], "lo": [0.0], "hi": [0.2]})
    md = stats.summary_markdown({"sensitivities": sens, "portfolio_beta": pbeta})
    section = md.split("## Top 10")[1]
    rows = [l for l in section.splitlines() if l.startswith("| T")]
    assert len(rows) == 10
    assert rows[0].startswith("| T11 |")           # |beta| = 12 is the largest eligible
    assert "T12" not in section
    assert "| robert | 0.1000 | 0.0000 | 0.2000 |" in md
