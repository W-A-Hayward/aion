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

# Materiality rule (fixed before looking at results; see docs/data_contract.md).
OIL_R2_MATERIAL = 0.10      # oil r2 at or above this is "material"
OIL_R2_LOW = 0.05           # threshold used for verdict_at_5
OIL_R2_HIGH = 0.15          # threshold used for verdict_at_15
OIL_P_NOT_LINKED = 0.05     # oil_p at or above this is "not linked"

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
    ("oil>ca2y", "oil", "ca2y", "brent", "dy:ca2y", "pp per 1.0 log"),
    ("oil>usdcad", "oil", "usdcad", "brent", "fx", "log per 1.0 log"),
    ("oil>breakeven", "oil", "breakeven", "brent", "dy:breakeven", "pp per 1.0 log"),
    ("us10y>TLT", "us10y", "TLT", "dy:us10y", "ret:TLT", "log per pp"),
    ("ca10y>XBB.TO", "ca10y", "XBB.TO", "dy:ca10y", "ret:XBB.TO", "log per pp"),
    ("ca2y>ZST.TO", "ca2y", "ZST.TO", "dy:ca2y", "ret:ZST.TO", "log per pp"),
    ("usdcad>VFV.TO", "usdcad", "VFV.TO", "fx", "ret:VFV.TO", "log per 1.0 log"),
    ("us10y>QQQ", "us10y", "QQQ", "dy:us10y", "ret:QQQ", "log per pp"),
    ("us10y>SHOP.TO", "us10y", "SHOP.TO", "dy:us10y", "ret:SHOP.TO", "log per pp"),
    ("ca10y>XLB.TO", "ca10y", "XLB.TO", "dy:ca10y", "ret:XLB.TO", "log per pp"),
    # Information only: nominal yields do not price real return bonds, so there is no chain.
    ("ca10y>XRB.TO", "ca10y", "XRB.TO", "dy:ca10y", "ret:XRB.TO", "log per pp"),
]

# ticker -> (chain label, link ids multiplied together)
CHAINS = {
    "TLT": ("oil>us10y>TLT", ["oil>us10y", "us10y>TLT"]),
    "XBB.TO": ("oil>ca10y>XBB.TO", ["oil>ca10y", "ca10y>XBB.TO"]),
    "ZST.TO": ("oil>ca2y>ZST.TO", ["oil>ca2y", "ca2y>ZST.TO"]),
    "VFV.TO": ("oil>usdcad>VFV.TO", ["oil>usdcad", "usdcad>VFV.TO"]),
    "QQQ": ("oil>us10y>QQQ", ["oil>us10y", "us10y>QQQ"]),
    "SHOP.TO": ("oil>us10y>SHOP.TO", ["oil>us10y", "us10y>SHOP.TO"]),
    "XLB.TO": ("oil>ca10y>XLB.TO", ["oil>ca10y", "ca10y>XLB.TO"]),
}

# ticker -> link id that gives the yield move for an oil move
DURATION_YIELD_LINK = {"TLT": "oil>us10y", "XBB.TO": "oil>ca10y", "ZST.TO": "oil>ca2y"}


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

    The weekly portfolio return is log(1 + sum(weight * (exp(ret_cad) - 1))) over the
    persona's holdings (a week is used only if every holding has a return). It is regressed on Brent with
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
        # Aggregate weighted SIMPLE returns, then go back to a log return.
        simple = np.exp(data.ret_cad[w.index]) - 1.0
        wsum = (simple * w).sum(axis=1, min_count=len(w))
        port = np.log1p(wsum.where(wsum > -1))
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

FX_DIAG_RANGE = (0.5, 1.5)


def fx_diagnostic(data: WeeklyData) -> dict:
    """Beta of (VFV.TO - XSP.TO) weekly log return on the weekly log change of usdcad.

    VFV.TO holds US stocks unhedged and XSP.TO is CAD-hedged, so the difference should
    move about one-for-one with usdcad. Returns beta, lo, hi, n and ok (beta in 0.5..1.5).
    """
    if "VFV.TO" not in data.ret_cad.columns or "XSP.TO" not in data.ret_cad.columns:
        return {"beta": np.nan, "lo": np.nan, "hi": np.nan, "n": 0, "ok": False}
    diff = data.ret_cad["VFV.TO"] - data.ret_cad["XSP.TO"]
    r = regress(diff, data.usdcad)
    ok = bool(pd.notna(r["beta"]) and FX_DIAG_RANGE[0] <= r["beta"] <= FX_DIAG_RANGE[1])
    return {"beta": r["beta"], "lo": r["lo"], "hi": r["hi"], "n": r["n"], "ok": ok}


def fx_diagnostic_lines(diag: dict) -> list[str]:
    """summary.md lines for the usdcad diagnostic, with a warning when outside 0.5..1.5."""
    lines = ["", "## Diagnostic: (VFV.TO - XSP.TO) weekly log return on weekly log change of usdcad", ""]
    if pd.isna(diag["beta"]):
        msg = "WARNING: diagnostic not available (VFV.TO or XSP.TO missing, or too few weeks); expected near +1."
        print(msg)
        return lines + [msg]
    lines.append(f"beta {diag['beta']:.4f}, range {diag['lo']:.4f} to {diag['hi']:.4f}, "
                 f"{diag['n']} weeks (expected near +1)")
    if not diag["ok"]:
        msg = (f"WARNING: usdcad diagnostic beta {diag['beta']:.4f} is outside "
               f"{FX_DIAG_RANGE[0]}..{FX_DIAG_RANGE[1]}.")
        print(msg)
        lines += ["", msg]
    return lines


def summary_markdown(tables: dict[str, pd.DataFrame], data: WeeklyData | None = None) -> str:
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
    if data is not None:
        lines += fx_diagnostic_lines(fx_diagnostic(data))
    if "risk_share" in tables:
        lines += risk_summary_lines(tables)
    lines += history_summary_lines(tables)
    return "\n".join(lines) + "\n"


def write_outputs(tables: dict[str, pd.DataFrame], bucket: str | None = None, s3=None,
                  data: WeeklyData | None = None) -> list[str]:
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
    s3.put_object(Bucket=bucket, Key=key, Body=summary_markdown(tables, data).encode("utf-8"),
                  ContentType="text/markdown")
    keys.append(key)
    return keys


# ---------------------------------------------------------------------------
# Step 12: risk share, stress history, contributions and materiality
# ---------------------------------------------------------------------------

STRESS_WINDOWS = (1, 4, 13)
STRESS_DIRECTIONS = ("oil_up", "oil_down")
STRESS_THRESHOLD_PCT = 10                 # window 1 default: top / bottom 10% of weeks
STRESS_EXTRA_THRESHOLDS_PCT = (5, 20)     # window 1 only
MAX_EPISODES = {4: 10, 13: 5}             # non-overlapping episodes for longer windows
NORMAL_SWING_WINDOW = 13
RATES_SERIES = "ca10y"                    # BD.CDN.10YR.DQ.YLD, weekly change in pp
STOCKS_TICKER = "XIU.TO"
FACTORS = ("oil", "rates", "stocks")

WEEKLY_RETURNS_COLUMNS = ["week", "subject_or_ticker", "ret_cad", "brent_ret"]
RISK_SHARE_COLUMNS = ["subject", "subject_type", "factor", "beta", "lo", "hi", "p", "r2", "n_weeks"]
STRESS_HISTORY_COLUMNS = [
    "subject", "subject_type", "window_weeks", "direction", "threshold_pct", "n_episodes",
    "avg_oil_move_pct", "avg_return_pct", "worst_return_pct", "worst_end_date",
    "per_100k_avg", "per_100k_worst", "episode_end_dates", "regimes",
]
STRESS_CONTRIBUTION_COLUMNS = [
    "persona", "ticker", "weight", "window_weeks", "direction",
    "avg_return_pct", "contribution_pct", "share_of_loss",
]
MATERIALITY_COLUMNS = [
    "subject", "subject_type", "verdict", "verdict_at_5", "verdict_at_15", "oil_r2", "oil_p",
    "stress13_avg_pct", "normal_swing13_pct", "n_episodes_13", "regimes", "reason_text",
]


@dataclass
class Subject:
    """A portfolio analysed as one unit: a persona or an alternative (after the swap)."""

    name: str
    subject_type: str          # "persona" | "alternative"
    weights: dict
    ret: pd.Series             # weekly portfolio log return (CAD)


def portfolio_log_return(ret_cad: pd.DataFrame, weights: dict) -> pd.Series:
    """log(1 + sum(weight * (exp(ret_cad) - 1))); NaN in a week when any holding has no return."""
    w = pd.Series(weights, dtype=float)
    simple = np.exp(ret_cad[list(w.index)]) - 1.0
    wsum = (simple * w).sum(axis=1, min_count=len(w))
    return np.log1p(wsum.where(wsum > -1))


def subject_weights() -> dict[str, tuple[str, dict]]:
    """name -> (subject_type, weights): the personas, then every alternative after its swap.

    Alternative names look like "robert:TLT->ZST.TO".
    """
    out: dict[str, tuple[str, dict]] = {p: ("persona", dict(h)) for p, h in PERSONAS.items()}
    for persona, holding, alt, shift in ALTERNATIVES:
        after = dict(PERSONAS[persona])
        moved = after[holding] if shift is None else shift
        after[holding] = after[holding] - moved
        if after[holding] <= 1e-12:
            del after[holding]
        after[alt] = after.get(alt, 0.0) + moved
        out[f"{persona}:{holding}->{alt}"] = ("alternative", after)
    return out


def build_subjects(data: WeeklyData) -> list[Subject]:
    """Weekly return series of every subject. A subject with a skipped ticker is left out (warning)."""
    subjects = []
    for name, (kind, weights) in subject_weights().items():
        missing = [t for t in weights if t not in data.ret_cad.columns]
        if missing:
            print(f"WARNING: no risk tables for {name}: no returns for {missing}")
            continue
        subjects.append(Subject(name, kind, weights, portfolio_log_return(data.ret_cad, weights)))
    return subjects


def weekly_returns_table(data: WeeklyData, subjects: list[Subject]) -> pd.DataFrame:
    """The weekly series used everywhere: week, subject_or_ticker, ret_cad, brent_ret (long format).

    Ticker rows come from data.ret_cad, subject rows are the portfolio log returns.
    Weeks with no return are left out.
    """
    series = {t: data.ret_cad[t] for t in data.ret_cad.columns}
    series.update({s.name: s.ret for s in subjects})
    parts = []
    for name, s in series.items():
        s = s.dropna()
        parts.append(pd.DataFrame({
            "week": [d.date() for d in s.index],
            "subject_or_ticker": name,
            "ret_cad": s.to_numpy(dtype=float),
            "brent_ret": data.brent.reindex(s.index).to_numpy(dtype=float),
        }))
    return pd.concat(parts, ignore_index=True)[WEEKLY_RETURNS_COLUMNS]


def factor_series(data: WeeklyData) -> dict[str, pd.Series]:
    """The three single factors: oil (Brent log return), rates (weekly change of the CA 10y yield, pp),
    stocks (XIU.TO weekly CAD log return)."""
    return {"oil": data.brent, "rates": data.dy[RATES_SERIES], "stocks": data.ret_cad[STOCKS_TICKER]}


def risk_share(data: WeeklyData, subjects: list[Subject]) -> pd.DataFrame:
    """Single-factor HAC(4) regressions of each subject's weekly return on oil, rates and stocks.

    r2 is the share of the subject's weekly variance explained by that factor alone. The three
    r2 values of one subject overlap (oil, rates and stocks move together) and do not add up.
    """
    factors = factor_series(data)
    rows = []
    for s in subjects:
        for factor in FACTORS:
            r = regress(s.ret, factors[factor])
            rows.append({"subject": s.name, "subject_type": s.subject_type, "factor": factor,
                         "beta": r["beta"], "lo": r["lo"], "hi": r["hi"], "p": r["p"],
                         "r2": r["r2"], "n_weeks": r["n"]})
    df = pd.DataFrame(rows, columns=RISK_SHARE_COLUMNS)
    return df.astype({"n_weeks": "Int64"})


# -- episodes ---------------------------------------------------------------

def window_sums(log_ret: pd.Series, window: int) -> pd.Series:
    """Rolling sum of `window` consecutive weekly log returns, labelled by the last week.

    Windows that are not made of consecutive Fridays (a missing week) are NaN.
    """
    if window == 1:
        return log_ret.copy()
    sums = log_ret.rolling(window).sum()
    idx = pd.Series(log_ret.index, index=log_ret.index)
    span = idx - idx.shift(window - 1)
    return sums.where(span == pd.Timedelta(days=7 * (window - 1)))


def pick_nonoverlapping(sums: pd.Series, window: int, max_n: int, largest: bool = True) -> list:
    """Greedy, non-overlapping selection of windows.

    `sums` holds one value per window end (position = week position in the weekly series).
    Candidates are visited from the largest (or smallest) value, ties by earlier date. A
    window is kept when its weeks do not overlap an already kept one. Returns up to `max_n`
    end labels in date order.
    """
    pos = pd.Series(np.arange(len(sums)), index=sums.index)
    valid = sums.dropna()
    order = valid.sort_values(ascending=not largest, kind="mergesort").index
    chosen: list = []
    for label in order:
        p = pos[label]
        if all(abs(p - pos[c]) >= window for c in chosen):
            chosen.append(label)
            if len(chosen) == max_n:
                break
    return sorted(chosen)


def select_episodes(brent: pd.Series, window: int, direction: str,
                    threshold_pct: float | None = None) -> list:
    """End weeks of the large oil moves.

    Window 1: the top (oil_up) or bottom (oil_down) `threshold_pct` percent of weeks by Brent log
    return (count rounded up). Windows 4 and 13: the largest (or most negative) rolling Brent
    sums, greedy and non-overlapping, up to MAX_EPISODES.
    """
    if direction not in STRESS_DIRECTIONS:
        raise ValueError(f"unknown direction: {direction}")
    largest = direction == "oil_up"
    brent = brent.dropna()
    if window == 1:
        k = max(1, int(np.ceil(len(brent) * float(threshold_pct) / 100.0)))
        order = brent.sort_values(ascending=not largest, kind="mergesort").index[:k]
        return sorted(order)
    return pick_nonoverlapping(window_sums(brent, window), window, MAX_EPISODES[window], largest)


def _simple_pct(log_sum) -> np.ndarray:
    return 100.0 * (np.exp(np.asarray(log_sum, dtype=float)) - 1.0)


def _years(ends: list) -> str:
    return ",".join(str(y) for y in sorted({pd.Timestamp(e).year for e in ends}))


def stress_history(subjects: list[Subject], brent: pd.Series) -> pd.DataFrame:
    """Realized returns of each subject in past large oil moves (descriptive only).

    Episodes are chosen from Brent on the weeks where both the subject and Brent have a return.
    Returns are simple returns in percent (compounded weekly portfolio returns). No p-values or
    confidence intervals: overlapping and clustered episodes are not independent observations.
    """
    rows = []
    for s in subjects:
        panel = pd.concat([s.ret.rename("s"), brent.rename("b")], axis=1).dropna()
        if panel.empty:
            continue
        specs = [(1, STRESS_THRESHOLD_PCT)] + [(1, t) for t in STRESS_EXTRA_THRESHOLDS_PCT]
        specs += [(4, None), (13, None)]
        for window, thr in specs:
            s_sum = window_sums(panel["s"], window)
            b_sum = window_sums(panel["b"], window)
            for direction in STRESS_DIRECTIONS:
                ends = select_episodes(panel["b"], window, direction, thr)
                if not ends:
                    continue
                ret = _simple_pct(s_sum.loc[ends])
                oil = _simple_pct(b_sum.loc[ends])
                worst = int(np.argmin(ret))
                rows.append({
                    "subject": s.name, "subject_type": s.subject_type,
                    "window_weeks": window, "direction": direction,
                    "threshold_pct": float(thr) if thr is not None else np.nan,
                    "n_episodes": len(ends),
                    "avg_oil_move_pct": float(oil.mean()),
                    "avg_return_pct": float(ret.mean()),
                    "worst_return_pct": float(ret[worst]),
                    "worst_end_date": pd.Timestamp(ends[worst]).date(),
                    "per_100k_avg": float(ret.mean()) * 1000.0,
                    "per_100k_worst": float(ret[worst]) * 1000.0,
                    "episode_end_dates": ",".join(pd.Timestamp(e).date().isoformat() for e in ends),
                    "regimes": _years(ends),
                })
    df = pd.DataFrame(rows, columns=STRESS_HISTORY_COLUMNS)
    return df.astype({"window_weeks": "Int64", "n_episodes": "Int64"})


def stress_contributions(data: WeeklyData, subjects: list[Subject]) -> pd.DataFrame:
    """Per-holding contribution to each persona's average return in the same oil episodes.

    Personas only; window 1 uses the 10% threshold. avg_return_pct is the ticker's own average
    simple return over the persona's episodes, contribution_pct = weight * avg_return_pct and
    share_of_loss = contribution / sum of the persona's contributions. The sum of contributions
    equals the portfolio average exactly for window 1 and within a small gap for 4 and 13 weeks
    (the portfolio return compounds weekly rebalanced returns, the tickers buy-and-hold).
    """
    rows = []
    for s in subjects:
        if s.subject_type != "persona":
            continue
        tickers = list(s.weights)
        panel = pd.concat([s.ret.rename("s"), data.brent.rename("b"), data.ret_cad[tickers]],
                          axis=1).dropna()
        for window in STRESS_WINDOWS:
            thr = STRESS_THRESHOLD_PCT if window == 1 else None
            for direction in STRESS_DIRECTIONS:
                ends = select_episodes(panel["b"], window, direction, thr)
                if not ends:
                    continue
                avg = {t: float(_simple_pct(window_sums(panel[t], window).loc[ends]).mean())
                       for t in tickers}
                contrib = {t: s.weights[t] * avg[t] for t in tickers}
                total = sum(contrib.values())
                for t in tickers:
                    rows.append({
                        "persona": s.name, "ticker": t, "weight": s.weights[t],
                        "window_weeks": window, "direction": direction,
                        "avg_return_pct": avg[t], "contribution_pct": contrib[t],
                        "share_of_loss": contrib[t] / total if abs(total) > 1e-9 else np.nan,
                    })
    df = pd.DataFrame(rows, columns=STRESS_CONTRIBUTION_COLUMNS)
    return df.astype({"window_weeks": "Int64"})


def normal_swing(log_ret: pd.Series, window: int = NORMAL_SWING_WINDOW) -> float:
    """Standard deviation (percent) of NON-OVERLAPPING `window`-week simple returns.

    Consecutive blocks of `window` weeks from the first week; an incomplete last block or a
    block with a missing week is dropped. NaN with fewer than 2 blocks.
    """
    s = log_ret.dropna()
    blocks = []
    for i in range(0, len(s) - window + 1, window):
        chunk = s.iloc[i:i + window]
        if chunk.index[-1] - chunk.index[0] == pd.Timedelta(days=7 * (window - 1)):
            blocks.append(float(_simple_pct(chunk.sum())))
    return float(np.std(blocks, ddof=1)) if len(blocks) >= 2 else np.nan


# -- materiality ------------------------------------------------------------

def materiality_verdict(oil_r2: float, oil_p: float, stress13_avg_pct: float,
                        normal_swing13_pct: float, r2_material: float = OIL_R2_MATERIAL) -> str:
    """The materiality rule.

    "not linked" if oil_p >= OIL_P_NOT_LINKED; "material" if oil_r2 >= r2_material or
    |stress13_avg_pct| > normal_swing13_pct; "measurable but minor" otherwise.
    A missing stress or swing value never makes a subject material by itself.
    """
    if pd.isna(oil_p) or pd.isna(oil_r2):
        raise ValueError("oil_p and oil_r2 are required for a verdict")
    if oil_p >= OIL_P_NOT_LINKED:
        return "not linked"
    stress_big = (pd.notna(stress13_avg_pct) and pd.notna(normal_swing13_pct)
                  and abs(stress13_avg_pct) > normal_swing13_pct)
    if oil_r2 >= r2_material or stress_big:
        return "material"
    return "measurable but minor"


def _reason_text(oil_r2, oil_p, avg, swing, n_ep, regimes) -> str:
    text = f"Oil explains {oil_r2 * 100:.1f}% of weekly moves"
    if oil_p >= OIL_P_NOT_LINKED:
        text += f" (not statistically distinguishable from zero, p = {oil_p:.2f})"
    if pd.isna(avg) or pd.isna(swing) or not n_ep:
        return text + "; there is not enough history for 13-week oil rises."
    years = f" ({regimes.replace(',', ', ')})" if regimes else ""
    size = abs(avg) - swing
    cmp_ = "more than" if size > 0 else ("the same as" if size == 0 else "less than")
    return (f"{text}; in the {int(n_ep)} largest 13-week oil rises{years} the portfolio averaged "
            f"{avg:.1f}%, {cmp_} its normal 13-week swing of {swing:.1f}%.")


def materiality(risk: pd.DataFrame, stress: pd.DataFrame, subjects: list[Subject]) -> pd.DataFrame:
    """One verdict per subject (plus the verdict at the 5% and 15% oil r2 thresholds)."""
    oil = risk[risk["factor"] == "oil"].set_index("subject")
    s13 = stress[(stress["window_weeks"] == 13) & (stress["direction"] == "oil_up")].set_index("subject")
    rows = []
    for s in subjects:
        if s.name not in oil.index:
            continue
        r2, p = float(oil.loc[s.name, "r2"]), float(oil.loc[s.name, "p"])
        if s.name in s13.index:
            avg = float(s13.loc[s.name, "avg_return_pct"])
            n_ep = int(s13.loc[s.name, "n_episodes"])
            regimes = str(s13.loc[s.name, "regimes"])
        else:
            avg, n_ep, regimes = np.nan, 0, ""
        swing = normal_swing(s.ret)
        rows.append({
            "subject": s.name, "subject_type": s.subject_type,
            "verdict": materiality_verdict(r2, p, avg, swing, OIL_R2_MATERIAL),
            "verdict_at_5": materiality_verdict(r2, p, avg, swing, OIL_R2_LOW),
            "verdict_at_15": materiality_verdict(r2, p, avg, swing, OIL_R2_HIGH),
            "oil_r2": r2, "oil_p": p, "stress13_avg_pct": avg, "normal_swing13_pct": swing,
            "n_episodes_13": n_ep, "regimes": regimes,
            "reason_text": _reason_text(r2, p, avg, swing, n_ep, regimes),
        })
    df = pd.DataFrame(rows, columns=MATERIALITY_COLUMNS)
    return df.astype({"n_episodes_13": "Int64"})


def build_risk_tables(data: WeeklyData) -> dict[str, pd.DataFrame]:
    """weekly_returns, risk_share, stress_history, stress_contributions and materiality."""
    subjects = build_subjects(data)
    risk = risk_share(data, subjects)
    stress = stress_history(subjects, data.brent)
    return {
        "weekly_returns": weekly_returns_table(data, subjects),
        "risk_share": risk,
        "stress_history": stress,
        "stress_contributions": stress_contributions(data, subjects),
        "materiality": materiality(risk, stress, subjects),
    }


def risk_summary_lines(tables: dict[str, pd.DataFrame]) -> list[str]:
    """summary.md section for the risk tables. Raises AssertionError when a persona has no rows
    in risk_share, stress_history, stress_contributions or materiality."""
    for name, col in (("risk_share", "subject"), ("stress_history", "subject"),
                      ("stress_contributions", "persona"), ("materiality", "subject")):
        have = set(tables[name][col])
        missing = sorted(set(PERSONAS) - have)
        if missing:
            raise AssertionError(f"personas without rows in {name}: {missing}")
    risk, stress, mat = tables["risk_share"], tables["stress_history"], tables["materiality"]
    r2 = risk.pivot(index="subject", columns="factor", values="r2")
    st = stress[(stress["direction"] == "oil_up")
                & (stress["window_weeks"].isin([1, 13]))
                & (stress["threshold_pct"].isna() | (stress["threshold_pct"] == STRESS_THRESHOLD_PCT))]
    st = st.set_index(["subject", "window_weeks"])

    def per100k(subject, w):
        if (subject, w) not in st.index:
            return "n/a"
        r = st.loc[(subject, w)]
        return f"{r['per_100k_avg']:,.0f} (worst {r['per_100k_worst']:,.0f})"

    lines = ["", "## Oil vs rates vs stocks, large oil rises and materiality", "",
             "r2 is the share of the subject's weekly variance explained by that factor alone. The three "
             "r2 values overlap (oil, rates and stocks move together) and do not add up.",
             "Stress figures are realized returns in past large oil rises, in dollars per $100k "
             "(window 1: top 10% of weeks; window 13: 5 non-overlapping 13-week rises). Descriptive only.", "",
             "| subject | oil r2 | rates r2 | stocks r2 | oil_up 1w per $100k | oil_up 13w per $100k "
             "| verdict | at 5% | at 15% |", "|---|---|---|---|---|---|---|---|---|"]
    for _, m in mat.iterrows():
        sub = m["subject"]
        lines.append(f"| {sub} | {r2.loc[sub, 'oil']:.3f} | {r2.loc[sub, 'rates']:.3f} "
                     f"| {r2.loc[sub, 'stocks']:.3f} | {per100k(sub, 1)} | {per100k(sub, 13)} "
                     f"| {m['verdict']} | {m['verdict_at_5']} | {m['verdict_at_15']} |")
    return lines


# ---------------------------------------------------------------------------
# Step 13: history tables (facts, protection, stock_bond, comovement)
# ---------------------------------------------------------------------------
# All of these use weekly CAD SIMPLE returns (expm1 of the weekly CAD log returns already built).
# Thresholds below are constants fixed before looking at results.

WORST_WEEKS_SHARE = 0.10          # "worst weeks" = bottom 10% of weeks (count rounded up)
CPI_SERIES = "CPIAUCSL"           # US CPI index, monthly
CPI_YOY_THRESHOLD_PCT = 3.0       # year-over-year inflation: high regime is >= 3.0, low is < 3.0
CPI_HIGH, CPI_LOW = "cpi_ge_3", "cpi_lt_3"
WORST_WINDOW_WEEKS = 13
STOCK_BOND_PAIRS = [("XIU.TO", "XBB.TO"), ("SPY", "TLT")]    # (stock side, bond side)
BOND_FUNDS = ("TLT", "XBB.TO", "ZST.TO")
PROTECTION_PERIODS = ("2022", "2026_ytd", "other")           # 2022 calendar year, 2026 YTD, rest
PROTECTION_YEAR, YTD_YEAR = 2022, 2026
CONTEXT_YIELD_COLUMNS = {"us10y": "us10y", "ca10y": "ca10y"}  # context name -> WeeklyData.dy column

CONTEXT_FIELDS = ["us10y_chg_pp", "ca10y_chg_pp", "brent_chg_pct", "xiu_chg_pct"]
FACTS_COLUMNS = (
    ["subject", "subject_type", "max_drawdown_pct", "drawdown_peak_date", "drawdown_trough_date",
     "recovery_date", "worst_year", "worst_year_return_pct", "worst_13w_return_pct", "worst_13w_end_date",
     "total_return_pct", "annualized_volatility_pct", "n_weeks"]
    + [f"dd_{c}" for c in CONTEXT_FIELDS] + [f"w13_{c}" for c in CONTEXT_FIELDS]
)
PROTECTION_COLUMNS = ["subject", "subject_type", "stock_side", "bond_side", "period", "n_weeks",
                      "avg_bond_return_pct", "avg_stock_return_pct", "n_worst_weeks"]
STOCK_BOND_COLUMNS = ["pair", "measure", "week", "correlation", "n_weeks"]
COMOVEMENT_COLUMNS = ["persona", "scope", "avg_pairwise_corr", "n_pairs", "n_weeks"]


def simple_returns(log_ret: pd.Series) -> pd.Series:
    """Weekly simple returns from weekly log returns, missing weeks dropped."""
    return np.expm1(log_ret.dropna())


def drawdown_stats(simple: pd.Series) -> dict:
    """Maximum drawdown of a weekly simple-return series.

    Wealth starts at 1.0 on the Friday before the first return. max_drawdown_pct is the most
    negative value of wealth / running peak - 1 (in percent, <= 0). drawdown_peak_date is the
    first date the running peak value was reached, drawdown_trough_date the date of the lowest
    point, recovery_date the first later date with wealth at or above the peak (None if never).
    With no loss at all the dates are None and the drawdown is 0.
    """
    s = simple.dropna().sort_index()
    out = {"max_drawdown_pct": np.nan, "drawdown_peak_date": None,
           "drawdown_trough_date": None, "recovery_date": None}
    if s.empty:
        return out
    base = s.index[0] - pd.Timedelta(days=7)
    wealth = pd.concat([pd.Series([1.0], index=[base]), (1.0 + s).cumprod()])
    peak = wealth.cummax()
    dd = wealth / peak - 1.0
    out["max_drawdown_pct"] = float(dd.min() * 100.0)
    if dd.min() >= 0:
        return out
    trough = dd.idxmin()
    peak_value = peak.loc[trough]
    before = wealth.loc[:trough]
    peak_date = before.index[before == peak_value][0]
    later = wealth.loc[trough:].iloc[1:]
    back = later.index[later >= peak_value]
    out["drawdown_peak_date"] = peak_date.date()
    out["drawdown_trough_date"] = trough.date()
    out["recovery_date"] = back[0].date() if len(back) else None
    return out


def worst_calendar_year(simple: pd.Series) -> tuple[int | None, float]:
    """(year, return in percent) of the worst FULL calendar year.

    A year counts only when the series covers it from its first week (on or before Jan 7) to
    its last (on or after Dec 25); partial years such as the first sample year and the current
    year are left out. Returns (None, NaN) when no full year exists.
    """
    s = simple.dropna().sort_index()
    if s.empty:
        return None, np.nan
    best_year, best = None, np.inf
    for year in sorted(set(s.index.year)):
        if s.index.min() > pd.Timestamp(year, 1, 7) or s.index.max() < pd.Timestamp(year, 12, 25):
            continue
        r = float(np.prod(1.0 + s[s.index.year == year]) - 1.0)
        if r < best:
            best_year, best = int(year), r
    return (best_year, best * 100.0) if best_year is not None else (None, np.nan)


def worst_window(simple: pd.Series, window: int = WORST_WINDOW_WEEKS) -> tuple:
    """(compounded return in percent, end date) of the worst run of `window` consecutive weeks."""
    s = simple.dropna().sort_index()
    sums = window_sums(np.log1p(s), window).dropna()
    if sums.empty:
        return np.nan, None
    end = sums.idxmin()
    return float(np.expm1(sums.loc[end]) * 100.0), end.date()


def context_changes(data: WeeklyData, start, end) -> dict:
    """Market moves over the weeks after `start` up to and including `end`.

    US and Canadian 10-year yield changes in percentage points, Brent and XIU.TO in percent
    (compounded). NaN when a week of the window is missing from the weekly data or start/end is None.
    """
    out = {k: np.nan for k in CONTEXT_FIELDS}
    if start is None or end is None:
        return out
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    n = int(round((end - start).days / 7))
    idx = data.brent.index
    mask = (idx > start) & (idx <= end)
    if n < 1 or int(mask.sum()) != n:
        return out
    out["us10y_chg_pp"] = float(data.dy["us10y"][mask].sum(min_count=n))
    out["ca10y_chg_pp"] = float(data.dy["ca10y"][mask].sum(min_count=n))
    out["brent_chg_pct"] = float(np.expm1(data.brent[mask].sum(min_count=n)) * 100.0)
    if STOCKS_TICKER in data.ret_cad.columns:
        out["xiu_chg_pct"] = float(np.expm1(data.ret_cad[STOCKS_TICKER][mask].sum(min_count=n)) * 100.0)
    return out


def facts_row(subject: Subject, data: WeeklyData) -> dict:
    """One facts row for a subject (persona or alternative)."""
    s = simple_returns(subject.ret)
    dd = drawdown_stats(s)
    year, year_ret = worst_calendar_year(s)
    w_ret, w_end = worst_window(s)
    row = {"subject": subject.name, "subject_type": subject.subject_type}
    row.update(dd)
    row.update({
        "worst_year": year, "worst_year_return_pct": year_ret,
        "worst_13w_return_pct": w_ret, "worst_13w_end_date": w_end,
        "total_return_pct": float((np.prod(1.0 + s) - 1.0) * 100.0) if len(s) else np.nan,
        "annualized_volatility_pct": float(s.std(ddof=1) * np.sqrt(52) * 100.0) if len(s) > 1 else np.nan,
        "n_weeks": int(len(s)),
    })
    for prefix, start, end in (
        ("dd", dd["drawdown_peak_date"], dd["drawdown_trough_date"]),
        ("w13", (pd.Timestamp(w_end) - pd.Timedelta(days=7 * WORST_WINDOW_WEEKS)) if w_end else None, w_end),
    ):
        for k, v in context_changes(data, start, end).items():
            row[f"{prefix}_{k}"] = v
    return row


def facts_table(data: WeeklyData, subjects: list[Subject]) -> pd.DataFrame:
    """facts: one row per subject (3 personas and the alternative portfolios)."""
    df = pd.DataFrame([facts_row(s, data) for s in subjects], columns=FACTS_COLUMNS)
    for c in ("drawdown_peak_date", "drawdown_trough_date", "recovery_date", "worst_13w_end_date"):
        df[c] = df[c].astype(object)
    df["worst_year"] = df["worst_year"].astype("Int64")
    return df.astype({"n_weeks": "Int64"})


def _period_labels(index: pd.DatetimeIndex) -> pd.Series:
    labels = np.where(index.year == PROTECTION_YEAR, PROTECTION_PERIODS[0],
                      np.where(index.year == YTD_YEAR, PROTECTION_PERIODS[1], PROTECTION_PERIODS[2]))
    return pd.Series(labels, index=index)


def protection_split(stock: pd.Series, bond: pd.Series, share: float = WORST_WEEKS_SHARE) -> pd.DataFrame:
    """Average bond-side return in the worst `share` of weeks for the stock side, by period.

    The worst weeks are picked over all common weeks (count rounded up, ties by earlier date),
    then split into 2022, 2026 YTD and all other weeks. Returns period, n_weeks,
    avg_bond_return_pct, avg_stock_return_pct and n_worst_weeks (the size of the whole set).
    """
    df = pd.concat([stock.rename("stock"), bond.rename("bond")], axis=1).dropna()
    k = int(np.ceil(share * len(df))) if len(df) else 0
    worst = df.sort_values("stock", kind="mergesort").head(k)
    period = _period_labels(worst.index)
    rows = []
    for p in PROTECTION_PERIODS:
        g = worst[(period == p).to_numpy()]
        rows.append({
            "period": p, "n_weeks": int(len(g)),
            "avg_bond_return_pct": float(g["bond"].mean() * 100.0) if len(g) else np.nan,
            "avg_stock_return_pct": float(g["stock"].mean() * 100.0) if len(g) else np.nan,
            "n_worst_weeks": int(k),
        })
    return pd.DataFrame(rows)


def _side_return(simple: pd.DataFrame, weights: dict) -> pd.Series:
    """Weekly return of a group of holdings with their weights rescaled to sum to 1."""
    w = pd.Series(weights, dtype=float)
    return (simple[list(w.index)] * (w / w.sum())).sum(axis=1, min_count=len(w))


def protection_table(data: WeeklyData) -> pd.DataFrame:
    """protection: bond-side average return in the stock side's worst weeks, by period.

    Subjects: each persona that holds a bond fund (stock side = its non-bond holdings, bond
    side = its bond funds, each side weighted by the persona weights rescaled to 1) and the
    pairs XIU.TO/XBB.TO and SPY/TLT. Missing tickers are skipped with a warning.
    """
    simple = np.expm1(data.ret_cad)
    rows = []

    def add(subject, kind, stock_label, bond_label, stock, bond):
        for r in protection_split(stock, bond).to_dict("records"):
            rows.append({"subject": subject, "subject_type": kind, "stock_side": stock_label,
                         "bond_side": bond_label, **r})

    for persona, weights in PERSONAS.items():
        bonds = {t: w for t, w in weights.items() if t in BOND_FUNDS}
        stocks = {t: w for t, w in weights.items() if t not in BOND_FUNDS}
        if not bonds or not stocks:
            continue
        missing = [t for t in list(bonds) + list(stocks) if t not in simple.columns]
        if missing:
            print(f"WARNING: no protection rows for {persona}: no returns for {missing}")
            continue
        add(persona, "persona", ",".join(stocks), ",".join(bonds),
            _side_return(simple, stocks), _side_return(simple, bonds))
    for stock_t, bond_t in STOCK_BOND_PAIRS:
        if stock_t not in simple.columns or bond_t not in simple.columns:
            print(f"WARNING: no protection rows for {stock_t}/{bond_t}: missing returns")
            continue
        add(f"{stock_t}/{bond_t}", "pair", stock_t, bond_t, simple[stock_t], simple[bond_t])
    return pd.DataFrame(rows, columns=PROTECTION_COLUMNS).astype({"n_weeks": "Int64", "n_worst_weeks": "Int64"})


def cpi_yoy_weekly(macro: pd.DataFrame, weeks: pd.DatetimeIndex) -> pd.Series:
    """US CPI year-over-year change in percent, monthly values forward-filled onto `weeks`.

    Each monthly observation (dated the first of its month) is compared with the one 12 months
    earlier. A week takes the latest observation dated on or before it. Weeks before the first
    year-over-year value are NaN.
    """
    m = macro[macro["series_id"] == CPI_SERIES]
    s = pd.Series(pd.to_numeric(m["value"], errors="coerce").to_numpy(),
                  index=pd.DatetimeIndex(pd.to_datetime(m["date"]))).dropna()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    prev = s.copy()
    prev.index = prev.index + pd.DateOffset(months=12)
    yoy = ((s / prev.reindex(s.index) - 1.0) * 100.0).dropna()
    weeks = pd.DatetimeIndex(weeks)
    return yoy.reindex(yoy.index.union(weeks)).ffill().reindex(weeks).rename("cpi_yoy_pct")


def _corr(a: pd.Series, b: pd.Series) -> tuple[float, int]:
    df = pd.concat([a, b], axis=1).dropna()
    if len(df) < 3 or df.iloc[:, 0].std() == 0 or df.iloc[:, 1].std() == 0:
        return np.nan, int(len(df))
    return float(df.iloc[:, 0].corr(df.iloc[:, 1])), int(len(df))


def rolling_correlation(a: pd.Series, b: pd.Series, window: int = ROLLING_WINDOW) -> pd.Series:
    """Rolling correlation of two weekly series over `window` weeks (weeks without a full window left out)."""
    df = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    return df["a"].rolling(window).corr(df["b"]).dropna()


def stock_bond_table(data: WeeklyData, macro: pd.DataFrame) -> pd.DataFrame:
    """stock_bond: 52-week rolling correlations and the correlation by inflation regime.

    Rows per pair (XIU.TO/XBB.TO, SPY/TLT): measure "rolling_52w" (one row per week, n_weeks =
    52), and measure "cpi_ge_3" / "cpi_lt_3" (week null): the full-sample correlation over weeks
    where US CPI year-over-year is >= / < CPI_YOY_THRESHOLD_PCT, with the number of weeks.
    Weekly CAD simple returns are used.
    """
    simple = np.expm1(data.ret_cad)
    cpi = cpi_yoy_weekly(macro, simple.index)
    rows = []
    for stock_t, bond_t in STOCK_BOND_PAIRS:
        if stock_t not in simple.columns or bond_t not in simple.columns:
            print(f"WARNING: no stock_bond rows for {stock_t}/{bond_t}: missing returns")
            continue
        pair = f"{stock_t}/{bond_t}"
        for week, c in rolling_correlation(simple[stock_t], simple[bond_t]).items():
            rows.append({"pair": pair, "measure": "rolling_52w", "week": week.date(),
                         "correlation": float(c), "n_weeks": ROLLING_WINDOW})
        for label, mask in ((CPI_HIGH, cpi >= CPI_YOY_THRESHOLD_PCT), (CPI_LOW, cpi < CPI_YOY_THRESHOLD_PCT)):
            c, n = _corr(simple[stock_t][mask], simple[bond_t][mask])
            rows.append({"pair": pair, "measure": label, "week": None, "correlation": c, "n_weeks": n})
    df = pd.DataFrame(rows, columns=STOCK_BOND_COLUMNS)
    df["week"] = df["week"].astype(object)
    return df.astype({"n_weeks": "Int64"})


def avg_pairwise_corr(simple: pd.DataFrame) -> tuple[float, int]:
    """(mean of the pairwise correlations between columns, number of pairs)."""
    k = simple.shape[1]
    if k < 2 or len(simple) < 3:
        return np.nan, k * (k - 1) // 2
    c = simple.corr().to_numpy()
    vals = c[np.triu_indices(k, 1)]
    return float(np.nanmean(vals)) if np.isfinite(vals).any() else np.nan, k * (k - 1) // 2


def comovement_table(data: WeeklyData) -> pd.DataFrame:
    """comovement: average pairwise correlation of each persona's holdings.

    scope "all" uses every week, "worst_10pct" the 10% worst weeks (rounded up) for the
    persona's portfolio return. n_weeks is the number of weeks used.
    """
    simple = np.expm1(data.ret_cad)
    rows = []
    for persona, weights in PERSONAS.items():
        missing = [t for t in weights if t not in simple.columns]
        if missing:
            print(f"WARNING: no comovement rows for {persona}: no returns for {missing}")
            continue
        h = simple[list(weights)].dropna()
        port = (h * pd.Series(weights, dtype=float)).sum(axis=1)
        k = int(np.ceil(WORST_WEEKS_SHARE * len(h))) if len(h) else 0
        worst = port.sort_values(kind="mergesort").head(k).index
        for scope, part in (("all", h), ("worst_10pct", h.loc[worst])):
            c, n_pairs = avg_pairwise_corr(part)
            rows.append({"persona": persona, "scope": scope, "avg_pairwise_corr": c,
                         "n_pairs": n_pairs, "n_weeks": int(len(part))})
    return pd.DataFrame(rows, columns=COMOVEMENT_COLUMNS).astype({"n_pairs": "Int64", "n_weeks": "Int64"})


def build_history_tables(data: WeeklyData, macro: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """facts, protection, stock_bond and comovement. `macro` is raw["macro"] (needs CPIAUCSL)."""
    return {
        "facts": facts_table(data, build_subjects(data)),
        "protection": protection_table(data),
        "stock_bond": stock_bond_table(data, macro),
        "comovement": comovement_table(data),
    }


def _cell(v, fmt: str = "{:.2f}") -> str:
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return "n/a"
    return v if isinstance(v, str) else fmt.format(v)


def _md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    return ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)] + \
           ["| " + " | ".join(r) + " |" for r in rows]


def history_summary_lines(tables: dict[str, pd.DataFrame]) -> list[str]:
    """summary.md sections for facts, protection, stock_bond and comovement (those present)."""
    lines: list[str] = []
    if "facts" in tables:
        f = tables["facts"]
        lines += ["", "## Facts: drawdowns, worst periods, return and volatility", "",
                  "Weekly CAD simple returns. recovery_date n/a means not recovered. worst_year covers full "
                  "calendar years only.", ""]
        lines += _md_table(
            ["subject", "max drawdown %", "peak", "trough", "recovered", "worst year", "worst year %",
             "worst 13w %", "13w end", "total return %", "ann. vol %"],
            [[r["subject"], _cell(r["max_drawdown_pct"]), _cell(r["drawdown_peak_date"]),
              _cell(r["drawdown_trough_date"]), _cell(r["recovery_date"]),
              _cell(None if pd.isna(r["worst_year"]) else str(int(r["worst_year"]))),
              _cell(r["worst_year_return_pct"]), _cell(r["worst_13w_return_pct"]),
              _cell(r["worst_13w_end_date"]), _cell(r["total_return_pct"]),
              _cell(r["annualized_volatility_pct"])] for _, r in f.iterrows()])
        lines += ["", "Market moves over the same dates (yields in pp, Brent and XIU.TO in %):", ""]
        ctx_rows = []
        for _, r in f.iterrows():
            for prefix, label in (("dd", "drawdown"), ("w13", "worst 13w")):
                ctx_rows.append([r["subject"], label] + [_cell(r[f"{prefix}_{c}"]) for c in CONTEXT_FIELDS])
        lines += _md_table(["subject", "window", "US 10y pp", "CA 10y pp", "Brent %", "XIU.TO %"], ctx_rows)
    if "protection" in tables:
        p = tables["protection"]
        lines += ["", "## Protection: bond side in the 10% worst weeks of the stock side", "",
                  "Average bond-side weekly return (%) in those weeks, by period, with the number of weeks.", ""]
        lines += _md_table(
            ["subject", "stock side", "bond side", "period", "weeks", "avg bond %", "avg stock %"],
            [[r["subject"], r["stock_side"], r["bond_side"], r["period"], str(int(r["n_weeks"])),
              _cell(r["avg_bond_return_pct"]), _cell(r["avg_stock_return_pct"])] for _, r in p.iterrows()])
    if "stock_bond" in tables:
        sb = tables["stock_bond"]
        lines += ["", "## Stock-bond correlation", "",
                  f"Weekly returns. CPI regimes use US CPI year-over-year (CPIAUCSL, forward-filled): "
                  f"high is >= {CPI_YOY_THRESHOLD_PCT:g}%, low is < {CPI_YOY_THRESHOLD_PCT:g}%. Weeks before "
                  "the first year-over-year value are in neither regime.", ""]
        rows = []
        for pair, g in sb.groupby("pair", sort=False):
            roll = g[g["measure"] == "rolling_52w"]["correlation"]
            reg = g.set_index("measure")
            rows.append([pair,
                         _cell(roll.iloc[-1] if len(roll) else None, "{:.3f}"),
                         _cell(roll.min() if len(roll) else None, "{:.3f}"),
                         _cell(roll.max() if len(roll) else None, "{:.3f}"),
                         _cell(reg["correlation"].get(CPI_HIGH), "{:.3f}"), _cell(reg["n_weeks"].get(CPI_HIGH), "{:.0f}"),
                         _cell(reg["correlation"].get(CPI_LOW), "{:.3f}"), _cell(reg["n_weeks"].get(CPI_LOW), "{:.0f}")])
        lines += _md_table(["pair", "52w latest", "52w min", "52w max", "corr CPI>=3", "weeks",
                            "corr CPI<3", "weeks"], rows)
    if "comovement" in tables:
        c = tables["comovement"]
        lines += ["", "## Comovement: average pairwise correlation of holdings", ""]
        lines += _md_table(
            ["persona", "scope", "avg pairwise corr", "pairs", "weeks"],
            [[r["persona"], r["scope"], _cell(r["avg_pairwise_corr"], "{:.3f}"), str(int(r["n_pairs"])),
              str(int(r["n_weeks"]))] for _, r in c.iterrows()])
    return lines
