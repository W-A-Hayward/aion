"""Oil-price sensitivity statistics for the cascade MVP.

Every function is deterministic and follows docs/data_contract.md. The notebook
compute/run_stats.ipynb calls these functions top to bottom.

Raw inputs are CSV files under s3://$BUCKET/raw/. Outputs are Parquet files at
s3://$BUCKET/processed/<table>/part-0.parquet.
"""

from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests

# ---------------------------------------------------------------------------
# Constants (from docs/data_contract.md)
# ---------------------------------------------------------------------------

# The 14 MVP tickers. Personas and alternatives only use these.
CORE_TICKERS = [
    "XIU.TO", "ENB.TO", "XOM", "TLT", "XBB.TO", "ZST.TO", "QQQ",
    "SHOP.TO", "SPY", "VFV.TO", "XSP.TO", "XESG.TO", "ATD.TO", "RY.TO",
]
# The first 18 come from raw/starter/prices_daily.csv; XRB.TO, XLB.TO and XEG.TO
# come from the latest raw/prices/snapshot=*/prices_daily_extra.csv.
EXTRA_TICKERS = [
    "CNQ.TO", "CNR.TO", "FTS.TO", "TD.TO", "MFC.TO", "CSU.TO",
    "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "JPM", "JNJ", "PG",
    "GLD", "AGG", "ESGV",
    "XRB.TO", "XLB.TO", "XEG.TO",
]
UNIVERSE = CORE_TICKERS + EXTRA_TICKERS
EXCLUDED_TICKERS = {"BTC-USD", "ETH-USD"}  # never part of the universe
assert not EXCLUDED_TICKERS & set(UNIVERSE)
assert len(set(UNIVERSE)) == len(UNIVERSE)

# Tickers skipped (with a printed warning) when they have fewer weekly returns.
MIN_WEEKLY_RETURNS = 150

# ETFs that are not single stocks: no market control (simple values are copied).
NO_MARKET_CONTROL = {
    "XIU.TO", "XESG.TO", "SPY", "VFV.TO", "XSP.TO",
    "GLD", "AGG", "ESGV", "XRB.TO", "XLB.TO", "XEG.TO",
}
US_MARKET = "SPY"        # control for USD tickers
CA_MARKET = "XIU.TO"     # control for CAD (.TO) tickers

# Effective duration in years, from issuer documents in raw/manual_docs/
DURATION_YEARS = {
    "TLT": 14.63,     # iShares fact sheet, as of 2026-09-30
    "XBB.TO": 6.72,   # iShares product page, as of 2026-10-23
    "ZST.TO": 0.40,   # BMO fact sheet, as of 2026-10-30
}

PERSONAS = {
    "robert": {"TLT": 0.30, "XBB.TO": 0.40, "ENB.TO": 0.15, "RY.TO": 0.15},
    "amira": {"QQQ": 0.50, "SHOP.TO": 0.25, "XIU.TO": 0.25},
    "mateo": {"XIU.TO": 0.50, "VFV.TO": 0.50},
}

# (persona, holding, alternative, weight moved). None = the whole holding.
ALTERNATIVES = [
    ("robert", "TLT", "ZST.TO", None),
    ("robert", "XBB.TO", "ZST.TO", None),
    ("mateo", "XIU.TO", "XESG.TO", None),
    ("mateo", "VFV.TO", "XSP.TO", None),
    ("amira", "QQQ", "XIU.TO", 0.25),
]

SHOCKS_PCT = [-30, -15, 15, 30]

SERIES_TO_NAME = {
    "DGS10": "us10y",
    "DGS2": "us2y",
    "BD.CDN.10YR.DQ.YLD": "ca10y",
    "BD.CDN.2YR.DQ.YLD": "ca2y",
}

HAC_LAGS = 4
MIN_OBS = 20
SAMPLE_START = "2021-11-19"
TRAIN_END = "2024-12-31"
TEST_START = "2025-01-01"
OOS_TOP_SHARE = 0.10
ROLLING_WINDOW = 52
Z95 = 1.96
SUMMARY_MAX_Q = 0.10     # summary.md lists tickers with q_simple below this
SUMMARY_TOP_N = 10

SENSITIVITY_COLUMNS = [
    "ticker", "beta_simple", "lo_simple", "hi_simple", "p_simple",
    "beta_mkt", "lo_mkt", "hi_mkt", "p_mkt", "market_ticker",
    "r2_incremental", "exxon_equiv",
    "beta_ex2022", "lo_ex2022", "hi_ex2022", "p_ex2022",
    "beta_up", "beta_down", "oos_hit_rate", "oos_n", "n_weeks",
    "q_simple", "universe",
]

# link_id -> (from_node, to_node, kind of y, unit)
# y is either a yield change ("dy:<name>"), usdcad log change ("fx"),
# or an asset CAD return ("ret:<ticker>"). x is one of "brent", "dy:<name>", "fx".
LINK_SPECS = [
    ("oil>us10y", "oil", "us10y", "brent", "dy:us10y", "pp per 1.0 log"),
    ("oil>ca10y", "oil", "ca10y", "brent", "dy:ca10y", "pp per 1.0 log"),
    ("oil>usdcad", "oil", "usdcad", "brent", "fx", "log per 1.0 log"),
    ("oil>breakeven", "oil", "breakeven", "brent", "dy:breakeven", "pp per 1.0 log"),
    ("us10y>TLT", "us10y", "TLT", "dy:us10y", "ret:TLT", "log per pp"),
    ("ca10y>XBB.TO", "ca10y", "XBB.TO", "dy:ca10y", "ret:XBB.TO", "log per pp"),
    ("ca10y>ZST.TO", "ca10y", "ZST.TO", "dy:ca10y", "ret:ZST.TO", "log per pp"),
    ("usdcad>VFV.TO", "usdcad", "VFV.TO", "fx", "ret:VFV.TO", "log per 1.0 log"),
    ("us10y>QQQ", "us10y", "QQQ", "dy:us10y", "ret:QQQ", "log per pp"),
    ("us10y>SHOP.TO", "us10y", "SHOP.TO", "dy:us10y", "ret:SHOP.TO", "log per pp"),
    ("ca10y>XLB.TO", "ca10y", "XLB.TO", "dy:ca10y", "ret:XLB.TO", "log per pp"),
    ("ca10y>XRB.TO", "ca10y", "XRB.TO", "dy:ca10y", "ret:XRB.TO", "log per pp"),
]

# ticker -> (chain label, link ids multiplied together)
CHAINS = {
    "TLT": ("oil>us10y>TLT", ["oil>us10y", "us10y>TLT"]),
    "XBB.TO": ("oil>ca10y>XBB.TO", ["oil>ca10y", "ca10y>XBB.TO"]),
    "ZST.TO": ("oil>ca10y>ZST.TO", ["oil>ca10y", "ca10y>ZST.TO"]),
    "VFV.TO": ("oil>usdcad>VFV.TO", ["oil>usdcad", "usdcad>VFV.TO"]),
    "QQQ": ("oil>us10y>QQQ", ["oil>us10y", "us10y>QQQ"]),
    "SHOP.TO": ("oil>us10y>SHOP.TO", ["oil>us10y", "us10y>SHOP.TO"]),
    "XLB.TO": ("oil>ca10y>XLB.TO", ["oil>ca10y", "ca10y>XLB.TO"]),
    "XRB.TO": ("oil>ca10y>XRB.TO", ["oil>ca10y", "ca10y>XRB.TO"]),
}

# ticker -> link id that gives the yield move for an oil move
DURATION_YIELD_LINK = {"TLT": "oil>us10y", "XBB.TO": "oil>ca10y", "ZST.TO": "oil>ca10y"}


# ---------------------------------------------------------------------------
# Step 1: load raw CSV files from S3
# ---------------------------------------------------------------------------

def _s3_client():
    """Return a boto3 S3 client (imported lazily so tests need no AWS setup)."""
    import boto3

    return boto3.client("s3")


def pick_latest_snapshot(names: list[str]) -> str | None:
    """Return the entry with the latest snapshot=YYYY-MM-DD date, or None."""
    dated = []
    for name in names:
        m = re.search(r"snapshot=(\d{4}-\d{2}-\d{2})", name)
        if m:
            dated.append((m.group(1), name))
    return max(dated)[1] if dated else None


def latest_snapshot_prefix(bucket: str, prefix: str, s3=None) -> str:
    """Find the latest snapshot=YYYY-MM-DD folder directly under `prefix`.

    `prefix` ends with "/", for example "raw/fred/". Returns the folder prefix.
    """
    s3 = s3 or _s3_client()
    names: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter="/"):
        names += [p["Prefix"] for p in page.get("CommonPrefixes", [])]
    latest = pick_latest_snapshot(names)
    if latest is None:
        raise FileNotFoundError(f"No snapshot=YYYY-MM-DD folder under s3://{bucket}/{prefix}")
    return latest


def read_csv_s3(bucket: str, key: str, s3=None, **kwargs) -> pd.DataFrame:
    """Read one CSV object from S3 into a DataFrame."""
    s3 = s3 or _s3_client()
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    return pd.read_csv(io.BytesIO(body), **kwargs)


def load_raw(bucket: str | None = None, s3=None) -> dict[str, pd.DataFrame]:
    """Load every raw CSV the statistics need.

    Returns a dict with keys prices_starter, prices_extra, fx, macro, brent,
    t10yie. The extra prices and the FRED files come from the latest snapshot.
    """
    bucket = bucket or os.environ["BUCKET"]
    s3 = s3 or _s3_client()
    prices_snap = latest_snapshot_prefix(bucket, "raw/prices/", s3)
    fred_snap = latest_snapshot_prefix(bucket, "raw/fred/", s3)
    return {
        "prices_starter": read_csv_s3(bucket, "raw/starter/prices_daily.csv", s3),
        "prices_extra": read_csv_s3(bucket, prices_snap + "prices_daily_extra.csv", s3),
        "fx": read_csv_s3(bucket, "raw/starter/fx_usdcad_daily.csv", s3),
        "macro": read_csv_s3(bucket, "raw/starter/macro_rates.csv", s3),
        "brent": read_csv_s3(bucket, fred_snap + "DCOILBRENTEU.csv", s3, dtype=str),
        "t10yie": read_csv_s3(bucket, fred_snap + "T10YIE.csv", s3, dtype=str),
    }


def parse_fred(df: pd.DataFrame) -> pd.Series:
    """Turn a two-column FRED CSV into a daily float Series.

    The first column is the date, the second the value. "." and empty values
    become NaN.
    """
    dates = pd.to_datetime(df.iloc[:, 0])
    values = pd.to_numeric(df.iloc[:, 1].replace(".", np.nan), errors="coerce")
    s = pd.Series(values.to_numpy(), index=pd.DatetimeIndex(dates), name=str(df.columns[1]))
    return s[~s.index.duplicated(keep="last")].sort_index()


# ---------------------------------------------------------------------------
# Step 2: weekly returns
# ---------------------------------------------------------------------------

@dataclass
class WeeklyData:
    """Weekly (W-FRI) series, all indexed by the weeks that have a Brent return.

    ret_local: log return of adj_close in the ticker's own currency.
    ret_cad: ret_local, plus the usdcad log change for USD tickers.
    brent: weekly log return of Brent (USD).
    usdcad: weekly log change of usdcad.
    dy: weekly change in percentage points (us10y, us2y, ca10y, ca2y, breakeven).
    currency: ticker -> "USD" or "CAD".
    """

    ret_local: pd.DataFrame
    ret_cad: pd.DataFrame
    brent: pd.Series
    usdcad: pd.Series
    dy: pd.DataFrame
    currency: pd.Series


def _weekly_last(obj):
    """Resample to W-FRI keeping the last available (non-missing) value."""
    return obj.resample("W-FRI").last()


def _log_return(levels):
    """Log change between consecutive weekly levels (non-positive levels give NaN)."""
    return np.log(levels.where(levels > 0)).diff()


def build_weekly(raw: dict[str, pd.DataFrame], min_returns: int = MIN_WEEKLY_RETURNS) -> WeeklyData:
    """Build the weekly return panel from the raw frames returned by load_raw.

    Keeps the tickers in UNIVERSE (never BTC-USD or ETH-USD), uses adj_close,
    resamples to W-FRI (last value), computes log returns (prices, Brent, USDCAD)
    and percentage-point changes (yields, T10YIE), converts USD tickers to CAD,
    and drops weeks with no Brent return. A ticker with no prices, or with fewer
    than `min_returns` weekly returns, is skipped and a warning is printed.
    """
    prices = pd.concat([raw["prices_starter"], raw["prices_extra"]], ignore_index=True)
    prices = prices[prices["ticker"].isin(UNIVERSE)].copy()
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.drop_duplicates(["date", "ticker"], keep="last")
    present = [t for t in UNIVERSE if t in set(prices["ticker"])]
    for t in UNIVERSE:
        if t not in present:
            print(f"WARNING: skipping {t}: no rows in raw prices")

    currency = prices.groupby("ticker")["currency"].agg(lambda s: s.iloc[-1]).reindex(present)
    adj = prices.pivot(index="date", columns="ticker", values="adj_close")[present].sort_index()
    ret_local = _log_return(_weekly_last(adj))

    fx = raw["fx"].copy()
    fx["date"] = pd.to_datetime(fx["date"])
    fx_daily = fx.drop_duplicates("date", keep="last").set_index("date")["usdcad"].sort_index()
    usdcad = _log_return(_weekly_last(fx_daily)).rename("usdcad")

    brent = _log_return(_weekly_last(parse_fred(raw["brent"].copy()))).rename("brent")

    macro = raw["macro"].copy()
    macro = macro[macro["series_id"].isin(SERIES_TO_NAME)]
    macro["date"] = pd.to_datetime(macro["date"])
    macro["value"] = pd.to_numeric(macro["value"], errors="coerce")
    macro = macro.drop_duplicates(["date", "series_id"], keep="last")
    yields = macro.pivot(index="date", columns="series_id", values="value").rename(columns=SERIES_TO_NAME)
    yields = yields.sort_index()
    breakeven = parse_fred(raw["t10yie"].copy())
    yields = pd.concat([yields, breakeven.rename("breakeven")], axis=1).sort_index()
    dy = _weekly_last(yields)[["us10y", "us2y", "ca10y", "ca2y", "breakeven"]].diff()

    weeks = brent.dropna().index
    weeks = weeks[weeks >= pd.Timestamp(SAMPLE_START)]
    ret_local = ret_local.reindex(weeks)
    fx_chg = usdcad.reindex(weeks)
    ret_cad = ret_local.copy()
    for t in present:
        if currency[t] == "USD":
            ret_cad[t] = ret_local[t] + fx_chg
    counts = ret_cad.notna().sum()
    short = [t for t in present if counts[t] < min_returns]
    for t in short:
        print(f"WARNING: skipping {t}: only {int(counts[t])} weekly returns (need {min_returns})")
    keep = [t for t in present if t not in short]
    ret_local, ret_cad, currency = ret_local[keep], ret_cad[keep], currency[keep]
    return WeeklyData(
        ret_local=ret_local,
        ret_cad=ret_cad,
        brent=brent.reindex(weeks),
        usdcad=fx_chg,
        dy=dy.reindex(weeks),
        currency=currency,
    )


# ---------------------------------------------------------------------------
# Regression helpers
# ---------------------------------------------------------------------------

def _nan_fit() -> dict:
    return {"beta": np.nan, "se": np.nan, "lo": np.nan, "hi": np.nan, "p": np.nan,
            "r2": np.nan, "alpha": np.nan, "n": 0}


def _fit_hac(y: pd.Series, xs: pd.DataFrame):
    """OLS of y on xs with a constant and Newey-West (4 lag) errors. None if too few rows."""
    df = pd.concat([y.rename("y"), xs], axis=1).dropna()
    if len(df) < MIN_OBS:
        return None, len(df)
    X = sm.add_constant(df[list(xs.columns)], has_constant="add")
    res = sm.OLS(df["y"], X).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
    return res, len(df)


def regress(y: pd.Series, x: pd.Series) -> dict:
    """Simple regression y = a + b*x with HAC (4 lags) standard errors.

    Returns beta, se, lo, hi (beta +/- 1.96*se), p, r2, alpha and n. All values
    are NaN (n = rows found) when fewer than MIN_OBS complete rows exist.
    """
    res, n = _fit_hac(y, x.rename("x").to_frame())
    if res is None:
        out = _nan_fit()
        out["n"] = n
        return out
    beta, se = float(res.params["x"]), float(res.bse["x"])
    return {"beta": beta, "se": se, "lo": beta - Z95 * se, "hi": beta + Z95 * se,
            "p": float(res.pvalues["x"]), "r2": float(res.rsquared),
            "alpha": float(res.params["const"]), "n": n}


def regress_with_control(y: pd.Series, x: pd.Series, control: pd.Series) -> dict:
    """Regression y = a + b*x + c*control with HAC errors; reports b and the model R2."""
    res, n = _fit_hac(y, pd.concat([x.rename("x"), control.rename("m")], axis=1))
    if res is None:
        out = _nan_fit()
        out["n"] = n
        return out
    beta, se = float(res.params["x"]), float(res.bse["x"])
    return {"beta": beta, "se": se, "lo": beta - Z95 * se, "hi": beta + Z95 * se,
            "p": float(res.pvalues["x"]), "r2": float(res.rsquared),
            "alpha": float(res.params["const"]), "n": n}


def _plain_slope(y: pd.Series, x: pd.Series) -> float:
    """OLS slope of y on x (no standard errors). NaN with fewer than 3 rows or no variance."""
    df = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    if len(df) < 3 or df["x"].var() == 0:
        return np.nan
    return float(df["x"].cov(df["y"]) / df["x"].var())


def market_ticker_for(ticker: str, currency: str) -> str:
    """Market control ticker: "none" for market ETFs, SPY for USD tickers, XIU.TO otherwise."""
    if ticker in NO_MARKET_CONTROL:
        return "none"
    return US_MARKET if currency == "USD" else CA_MARKET


# ---------------------------------------------------------------------------
# Step 3: sensitivities
# ---------------------------------------------------------------------------

def out_of_sample(y: pd.Series, x: pd.Series) -> tuple[float, int]:
    """Out-of-sample sign hit rate on the largest oil moves.

    Fits y = a + b*x on weeks <= 2024-12-31. On weeks >= 2025-01-01 keeps the top
    10% (rounded up) by |x| and returns (share where sign(prediction) equals
    sign(actual), number of weeks kept). Returns (NaN, 0) if there is not enough data.
    """
    df = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    train = df[df.index <= pd.Timestamp(TRAIN_END)]
    test = df[df.index >= pd.Timestamp(TEST_START)]
    if len(train) < MIN_OBS or test.empty or train["x"].var() == 0:
        return np.nan, 0
    b = train["x"].cov(train["y"]) / train["x"].var()
    a = train["y"].mean() - b * train["x"].mean()
    k = max(1, int(np.ceil(OOS_TOP_SHARE * len(test))))
    order = test["x"].abs().sort_values(ascending=False, kind="mergesort").index[:k]
    top = test.loc[order]
    pred = a + b * top["x"]
    hit = np.sign(pred) == np.sign(top["y"])
    return float(hit.mean()), int(k)


def bh_adjust(p: pd.Series) -> pd.Series:
    """Benjamini-Hochberg adjusted p-values (q-values) across a Series of p-values.

    Missing p-values stay missing and are not counted in the number of tests.
    """
    out = pd.Series(np.nan, index=p.index, dtype=float)
    ok = p.notna()
    if ok.any():
        out[ok] = multipletests(p[ok].to_numpy(dtype=float), method="fdr_bh")[1]
    return out


def sensitivities(data: WeeklyData) -> pd.DataFrame:
    """Per-ticker oil sensitivity table (ret_cad on Brent) for every ticker in the data.

    Columns follow the data contract: simple and market-controlled betas with 95%
    ranges and p-values, incremental R2, Exxon-equivalent, beta excluding 2022,
    up/down betas, out-of-sample sign hit rate, and number of weeks. For tickers
    with no market control the market-controlled values copy the simple ones and
    market_ticker is "none"; r2_incremental is then the simple R2 (market-only R2 is 0).
    q_simple is the Benjamini-Hochberg adjusted p_simple across all tickers (p_simple is
    unchanged). universe is "core" or "extra".
    """
    x = data.brent
    rows = []
    tickers = list(data.ret_cad.columns)
    simple = {t: regress(data.ret_cad[t], x) for t in tickers}
    xom_beta = simple["XOM"]["beta"] if "XOM" in simple else np.nan
    for t in tickers:
        y = data.ret_cad[t]
        s = simple[t]
        mkt_t = market_ticker_for(t, data.currency[t])
        if mkt_t == "none":
            m = s
            r2_inc = s["r2"]
        elif mkt_t not in data.ret_cad.columns:   # market ticker was skipped
            m = _nan_fit()
            r2_inc = np.nan
        else:
            m = regress_with_control(y, x, data.ret_cad[mkt_t])
            mkt_only, _ = _fit_hac(y, data.ret_cad[mkt_t].rename("m").to_frame())
            r2_mkt_only = float(mkt_only.rsquared) if mkt_only is not None else np.nan
            # R2 with brent comes from the market-controlled model, so it is nested.
            r2_inc = m["r2"] - r2_mkt_only
        keep = x.index.year != 2022
        e = regress(y[keep], x[keep])
        up = x > 0
        down = x < 0
        hit, oos_n = out_of_sample(y, x)
        exxon = (s["beta"] / xom_beta
                 if pd.notna(xom_beta) and abs(xom_beta) >= 1e-6 else np.nan)
        rows.append({
            "ticker": t,
            "beta_simple": s["beta"], "lo_simple": s["lo"], "hi_simple": s["hi"], "p_simple": s["p"],
            "beta_mkt": m["beta"], "lo_mkt": m["lo"], "hi_mkt": m["hi"], "p_mkt": m["p"],
            "market_ticker": mkt_t,
            "r2_incremental": r2_inc,
            "exxon_equiv": exxon,
            "beta_ex2022": e["beta"], "lo_ex2022": e["lo"], "hi_ex2022": e["hi"], "p_ex2022": e["p"],
            "beta_up": _plain_slope(y[up], x[up]),
            "beta_down": _plain_slope(y[down], x[down]),
            "oos_hit_rate": hit, "oos_n": oos_n, "n_weeks": s["n"],
            "universe": "core" if t in CORE_TICKERS else "extra",
        })
    df = pd.DataFrame(rows)
    df["q_simple"] = bh_adjust(df["p_simple"])
    df = df[SENSITIVITY_COLUMNS]
    return df.astype({"oos_n": "Int64", "n_weeks": "Int64"})


# ---------------------------------------------------------------------------
# Step 4: rolling beta
# ---------------------------------------------------------------------------

def rolling_betas(data: WeeklyData, window: int = ROLLING_WINDOW) -> pd.DataFrame:
    """Rolling simple beta of ret_cad on Brent over `window` weeks, per ticker.

    Returns the long table (ticker, week, beta_52w, universe). Weeks without a full
    window are left out.
    """
    x = data.brent
    parts = []
    for t in data.ret_cad.columns:
        df = pd.concat([data.ret_cad[t].rename("y"), x.rename("x")], axis=1).dropna()
        beta = df["y"].rolling(window).cov(df["x"]) / df["x"].rolling(window).var()
        beta = beta.dropna()
        parts.append(pd.DataFrame({
            "ticker": t,
            "week": [d.date() for d in beta.index],
            "beta_52w": beta.to_numpy(),
            "universe": "core" if t in CORE_TICKERS else "extra",
        }))
    return pd.concat(parts, ignore_index=True)


# ---------------------------------------------------------------------------
# Step 5: links
# ---------------------------------------------------------------------------

def _series_for(data: WeeklyData, spec: str) -> pd.Series:
    """Resolve a link variable ("brent", "fx", "dy:<name>", "ret:<ticker>") to a weekly Series."""
    if spec == "brent":
        return data.brent
    if spec == "fx":
        return data.usdcad
    kind, name = spec.split(":", 1)
    if kind == "dy":
        return data.dy[name]
    if kind == "ret":
        return data.ret_cad[name]
    raise ValueError(f"Unknown link variable: {spec}")


def links(data: WeeklyData) -> pd.DataFrame:
    """Single-step regressions along the oil transmission chains.

    One row per link: link_id, from_node, to_node, beta, lo, hi, p, unit. A link
    whose ticker was skipped (too little history) is left out.
    """
    rows = []
    for link_id, frm, to, x_spec, y_spec, unit in LINK_SPECS:
        if any(sp.startswith("ret:") and sp[4:] not in data.ret_cad.columns for sp in (x_spec, y_spec)):
            continue
        r = regress(_series_for(data, y_spec), _series_for(data, x_spec))
        rows.append({"link_id": link_id, "from_node": frm, "to_node": to,
                     "beta": r["beta"], "lo": r["lo"], "hi": r["hi"], "p": r["p"], "unit": unit})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Step 6: chain reconciliation
# ---------------------------------------------------------------------------

def chain_reconciliation(links_df: pd.DataFrame, sens: pd.DataFrame) -> pd.DataFrame:
    """Compare the product of link betas with the direct oil beta.

    share_explained = beta_chain / beta_direct, NaN if |beta_direct| < 1e-6.
    """
    link_beta = links_df.set_index("link_id")["beta"]
    direct = sens.set_index("ticker")["beta_simple"]
    rows = []
    for ticker, (chain, ids) in CHAINS.items():
        if ticker not in direct.index or not all(i in link_beta.index for i in ids):
            continue
        beta_chain = float(np.prod([link_beta[i] for i in ids]))
        bd = float(direct[ticker])
        share = beta_chain / bd if abs(bd) >= 1e-6 else np.nan
        rows.append({"ticker": ticker, "chain": chain, "beta_direct": bd,
                     "beta_chain": beta_chain, "share_explained": share})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Step 7: duration check
# ---------------------------------------------------------------------------

def duration_check(links_df: pd.DataFrame, sens: pd.DataFrame, oil_move: float = 0.10) -> pd.DataFrame:
    """Compare the duration-implied price move with the measured one for a +10% Brent move.

    yield move (bp) = link beta (pp per 1.0 log) * log(1.10) * 100.
    implied_move_pct = -duration * yield move in pp.
    measured_move_pct = beta_simple * log(1.10) * 100.
    """
    link_beta = links_df.set_index("link_id")["beta"]
    direct = sens.set_index("ticker")["beta_simple"]
    shock = np.log(1 + oil_move)
    rows = []
    for ticker, duration in DURATION_YEARS.items():
        if ticker not in direct.index or DURATION_YIELD_LINK[ticker] not in link_beta.index:
            continue
        yield_bp = float(link_beta[DURATION_YIELD_LINK[ticker]]) * shock * 100
        rows.append({
            "ticker": ticker,
            "duration_years": duration,
            "yield_move_per_10pct_oil_bp": yield_bp,
            "implied_move_pct": -duration * yield_bp / 100,
            "measured_move_pct": float(direct[ticker]) * shock * 100,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Step 8: personas and portfolio exposure
# ---------------------------------------------------------------------------

def persona_holdings() -> pd.DataFrame:
    """The demo personas' holdings from the data contract: persona, ticker, weight."""
    rows = [{"persona": p, "ticker": t, "weight": w}
            for p, holdings in PERSONAS.items() for t, w in holdings.items()]
    return pd.DataFrame(rows)


def portfolio_exposure(holdings: pd.DataFrame, sens: pd.DataFrame) -> pd.DataFrame:
    """Join holdings to simple betas: persona, ticker, weight, beta, lo, hi, contribution.

    beta, lo and hi are the ticker's own simple beta and 95% range. contribution =
    weight * beta; summing contributions per persona gives the portfolio beta.
    """
    s = sens.set_index("ticker")[["beta_simple", "lo_simple", "hi_simple"]]
    out = holdings.copy()
    out["beta"] = out["ticker"].map(s["beta_simple"])
    out["lo"] = out["ticker"].map(s["lo_simple"])
    out["hi"] = out["ticker"].map(s["hi_simple"])
    out["contribution"] = out["weight"] * out["beta"]
    return out[["persona", "ticker", "weight", "beta", "lo", "hi", "contribution"]]


PORTFOLIO_BETA_COLUMNS = ["persona", "beta", "lo", "hi", "p", "r2", "n_weeks"]


def portfolio_beta(data: WeeklyData, holdings: pd.DataFrame) -> pd.DataFrame:
    """Oil beta of each persona's portfolio, from the portfolio's own weekly return.

    The weekly portfolio return is sum(weight * ret_cad) over the persona's holdings
    (a week is used only if every holding has a return). It is regressed on Brent with
    the same HAC(4) OLS as the tickers. Returns persona, beta, lo, hi, p, r2, n_weeks.
    A persona holding a ticker that was skipped (too little history) is left out and
    a warning is printed.
    """
    rows = []
    for persona, h in holdings.groupby("persona", sort=False):
        missing = [t for t in h["ticker"] if t not in data.ret_cad.columns]
        if missing:
            print(f"WARNING: no portfolio_beta for {persona}: no returns for {missing}")
            continue
        w = h.set_index("ticker")["weight"]
        port = (data.ret_cad[w.index] * w).sum(axis=1, min_count=len(w))
        r = regress(port, data.brent)
        rows.append({"persona": persona, "beta": r["beta"], "lo": r["lo"], "hi": r["hi"],
                     "p": r["p"], "r2": r["r2"], "n_weeks": r["n"]})
    df = pd.DataFrame(rows, columns=PORTFOLIO_BETA_COLUMNS)
    return df.astype({"n_weeks": "Int64"})


# ---------------------------------------------------------------------------
# Step 9: scenarios
# ---------------------------------------------------------------------------

def shock_impact_pct(beta, shock_pct):
    """Percent price impact of an oil shock: 100*(exp(beta*log(1+shock/100)) - 1)."""
    return 100.0 * (np.exp(np.asarray(beta, dtype=float) * np.log(1 + shock_pct / 100.0)) - 1.0)


def scenarios(sens: pd.DataFrame, pbeta: pd.DataFrame) -> pd.DataFrame:
    """Oil shock scenarios (-30, -15, +15, +30 %) for every persona and every ticker.

    Persona rows use the portfolio_beta table (beta, lo, hi); ticker rows use the
    simple beta and range from sensitivities.

    impact_pct uses the beta; lo_pct and hi_pct are the smaller and larger of the
    impacts at the two ends of the beta range (the order flips for negative shocks).
    """
    subjects = []
    for _, r in pbeta.iterrows():
        subjects.append((r["persona"], "persona", r["beta"], r["lo"], r["hi"]))
    for _, r in sens.iterrows():
        subjects.append((r["ticker"], "ticker", r["beta_simple"], r["lo_simple"], r["hi_simple"]))
    rows = []
    for name, kind, beta, lo, hi in subjects:
        for shock in SHOCKS_PCT:
            a, b = float(shock_impact_pct(lo, shock)), float(shock_impact_pct(hi, shock))
            rows.append({
                "subject": name, "subject_type": kind, "shock_pct": shock,
                "impact_pct": float(shock_impact_pct(beta, shock)),
                "lo_pct": min(a, b), "hi_pct": max(a, b),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Step 10: alternatives
# ---------------------------------------------------------------------------

def alternatives(holdings: pd.DataFrame, sens: pd.DataFrame) -> pd.DataFrame:
    """Effect of swapping one holding for an alternative, per the data contract pairs.

    The swap moves the whole holding weight (or the listed shift) to the alternative.
    Reports both betas and the +30% oil impact on the persona portfolio before and after.
    """
    beta = sens.set_index("ticker")["beta_simple"]
    rows = []
    for persona, holding, alt, shift in ALTERNATIVES:
        if holding not in beta.index or alt not in beta.index:
            continue
        before = holdings[holdings["persona"] == persona].set_index("ticker")["weight"].to_dict()
        moved = before[holding] if shift is None else shift
        after = dict(before)
        after[holding] = after[holding] - moved
        after[alt] = after.get(alt, 0.0) + moved
        beta_before = sum(w * beta[t] for t, w in before.items())
        beta_after = sum(w * beta[t] for t, w in after.items())
        rows.append({
            "persona": persona, "holding": holding, "alternative": alt,
            "beta_holding": float(beta[holding]), "beta_alternative": float(beta[alt]),
            "impact30_before_pct": float(shock_impact_pct(beta_before, 30)),
            "impact30_after_pct": float(shock_impact_pct(beta_after, 30)),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Step 11: write to S3
# ---------------------------------------------------------------------------

def summary_markdown(tables: dict[str, pd.DataFrame]) -> str:
    """Build summary.md text: row counts, portfolio betas, and the strongest oil-sensitive tickers.

    The last table lists the 10 tickers with the largest |beta_simple| among those with
    q_simple < 0.10.
    """
    lines = ["# cascade processed tables", "", "## Row counts", "",
             "| table | rows |", "|---|---|"]
    lines += [f"| {name} | {len(df)} |" for name, df in tables.items()]
    lines += ["", "## Portfolio betas (weekly portfolio CAD return regressed on weekly Brent log return)", "",
              "| persona | beta | lo | hi |", "|---|---|---|---|"]
    for _, r in tables["portfolio_beta"].iterrows():
        lines.append(f"| {r['persona']} | {r['beta']:.4f} | {r['lo']:.4f} | {r['hi']:.4f} |")
    sens = tables["sensitivities"]
    sig = sens[sens["q_simple"] < SUMMARY_MAX_Q]
    top = sig.reindex(sig["beta_simple"].abs().sort_values(ascending=False, kind="mergesort").index)
    top = top.head(SUMMARY_TOP_N)
    lines += ["", f"## Top {SUMMARY_TOP_N} tickers by |beta_simple| with q_simple < {SUMMARY_MAX_Q:.2f}", "",
              "| ticker | beta | range (lo to hi) | p_ex2022 | oos_hit_rate |", "|---|---|---|---|---|"]
    for _, r in top.iterrows():
        lines.append(f"| {r['ticker']} | {r['beta_simple']:.4f} | {r['lo_simple']:.4f} to {r['hi_simple']:.4f} "
                     f"| {r['p_ex2022']:.4f} | {r['oos_hit_rate']:.2f} |")
    if top.empty:
        lines.append("| (none) | | | | |")
    return "\n".join(lines) + "\n"


def write_outputs(tables: dict[str, pd.DataFrame], bucket: str | None = None, s3=None) -> list[str]:
    """Write each table to s3://bucket/processed/<table>/part-0.parquet and a summary.md.

    Existing objects are overwritten. The summary goes to
    processed/_summary/summary.md. Returns the list of keys written.
    """
    bucket = bucket or os.environ["BUCKET"]
    s3 = s3 or _s3_client()
    keys = []
    for name, df in tables.items():
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        key = f"processed/{name}/part-0.parquet"
        s3.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
        keys.append(key)
    key = "processed/_summary/summary.md"
    s3.put_object(Bucket=bucket, Key=key, Body=summary_markdown(tables).encode("utf-8"),
                  ContentType="text/markdown")
    keys.append(key)
    return keys
