"""
fetch_to_s3.py - MVP ingestion for the oil-exposure agent.

Uploads to s3://$BUCKET/raw/ :
  - the organizers' starter pack (local folder)            -> raw/starter/
  - Brent spot + US 10y breakeven inflation (FRED, EIA/Fed) -> raw/fred/
  - prices for VFV.TO, XSP.TO, XESG.TO (yfinance)           -> raw/prices/
  - holdings files for XIU and XESG (BlackRock Canada)       -> raw/holdings/
  - manifest.csv (source, URL, retrieval time, sha256 of every file)

Usage (SageMaker AI notebook terminal; AWS access comes from the notebook's IAM role):
    pip install -r requirements.txt
    export BUCKET=cascade-s3-bucket
    python ingest/fetch_to_s3.py --starter-dir data/alphaforge_starter
    python ingest/fetch_to_s3.py --starter-dir data/alphaforge_starter --no-upload   # local check only

Manual fallbacks (the script uses data/manual/<file> first when it exists):
  - FRED sometimes times out from AWS. Open https://fred.stlouisfed.org/series/DCOILBRENTEU and
    .../series/T10YIE in a browser -> Download -> CSV, save as data/manual/DCOILBRENTEU.csv and
    data/manual/T10YIE.csv, rerun.
  - Holdings: click "Download holdings" on the fund page, save as data/manual/xiu_holdings.csv or
    data/manual/xesg_holdings.csv, rerun.
"""
import argparse
import csv
import hashlib
import io
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests

TODAY = date.today().isoformat()
OUT = Path("data/out")            # everything written here mirrors the S3 layout
MANUAL = Path("data/manual")
START, END = "2021-11-12", "2026-11-13"   # same window as the starter pack

FRED_SERIES = {
    "DCOILBRENTEU": "Brent spot price, USD/bbl (U.S. EIA via FRED)",
    "T10YIE": "US 10-year breakeven inflation rate, % (Federal Reserve Bank of St. Louis via FRED)",
}
NEW_TICKERS = ["VFV.TO", "XSP.TO", "XESG.TO", "XRB.TO", "XLB.TO", "XEG.TO"]

# BlackRock Canada product pages; the CSV link below is the site's export link and may change.
HOLDINGS = {
    "xiu": ("https://www.blackrock.com/ca/investors/en/products/239832/"
            "ishares-sptsx-60-index-etf/1464253357814.ajax?fileType=csv&fileName=XIU_holdings&dataType=fund"),
    "xesg": ("https://www.blackrock.com/ca/investors/en/products/307298/"
             "ishares-esg-aware-msci-canada-index-etf/1464253357814.ajax?fileType=csv&fileName=XESG_holdings&dataType=fund"),
}

MANIFEST = []
MISSING = []   # inputs that could not be fetched


def save(content: bytes, rel_path: str, source: str, url: str, note: str = ""):
    path = OUT / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    MANIFEST.append({
        "path": rel_path, "source": source, "url": url, "note": note,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(),
    })
    print(f"  saved {rel_path} ({len(content):,} bytes)")


def get(url: str, tries: int = 3, timeout: int = 30) -> bytes:
    """GET with retries and backoff (5 s, 10 s). Raises the last error if every try fails."""
    for i in range(tries):
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (datathon research)"}, timeout=timeout)
            r.raise_for_status()
            return r.content
        except requests.RequestException as e:
            if i == tries - 1:
                raise
            print(f"  retry {i + 1}/{tries - 1} after error: {type(e).__name__}")
            time.sleep(5 * (i + 1))


def copy_starter(starter_dir: Path):
    files = [p for p in starter_dir.iterdir() if p.is_file()]
    if not files:
        sys.exit(f"No files in {starter_dir}")
    for p in files:
        save(p.read_bytes(), f"raw/starter/{p.name}", "PolyFinances starter pack", "provided by organizers")


def fetch_fred():
    for sid, label in FRED_SERIES.items():
        # cosd/coed limit the download to our window: smaller, faster response
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={START}&coed={END}"
        manual = MANUAL / f"{sid}.csv"
        if manual.exists():
            content, src = manual.read_bytes(), f"manual download from https://fred.stlouisfed.org/series/{sid}"
        else:
            try:
                content, src = get(url), url
            except requests.RequestException as e:
                print(f"  {sid}: download failed ({type(e).__name__}). Download the CSV from "
                      f"https://fred.stlouisfed.org/series/{sid} and save it as {manual}, then rerun.")
                MISSING.append(sid)
                continue
        save(content, f"raw/fred/snapshot={TODAY}/{sid}.csv", "FRED", src, label)


def fetch_prices():
    import yfinance as yf
    px = yf.download(NEW_TICKERS, start=START, end=END, auto_adjust=False,
                     group_by="ticker", progress=False)
    rows = []
    for t in NEW_TICKERS:
        d = px[t].dropna(subset=["Close"]).reset_index()
        if d.empty:
            print(f"  WARNING: no data for {t}")
            continue
        d = d.rename(columns={"Date": "date", "Open": "open", "High": "high", "Low": "low",
                              "Close": "close", "Adj Close": "adj_close", "Volume": "volume"})
        d["ticker"], d["currency"] = t, "CAD"
        rows.append(d[["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "currency"]])
    out = pd.concat(rows)
    save(out.to_csv(index=False).encode(), f"raw/prices/snapshot={TODAY}/prices_daily_extra.csv",
         "Yahoo Finance via yfinance", "yfinance", "same columns as the starter pack's prices_daily.csv")


def fetch_holdings():
    for name, url in HOLDINGS.items():
        manual = MANUAL / f"{name}_holdings.csv"
        if manual.exists():
            content, src = manual.read_bytes(), "manual download from blackrock.com/ca"
        else:
            try:
                content, src = get(url), url
            except requests.RequestException as e:
                print(f"  {name}: automatic download failed ({type(e).__name__}). Save it by hand to {manual} and rerun.")
                MISSING.append(name)
                continue
        if b"Ticker" not in content[:5000]:
            print(f"  {name}: file doesn't look like a holdings CSV. Save it by hand to {manual} and rerun.")
            MISSING.append(name)
            continue
        save(content, f"raw/holdings/snapshot={TODAY}/{name}_holdings.csv", "BlackRock iShares Canada", src)


def write_manifest():
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(MANIFEST[0].keys()))
    w.writeheader()
    w.writerows(MANIFEST)
    (OUT / "raw").mkdir(parents=True, exist_ok=True)
    (OUT / "raw/manifest.csv").write_text(buf.getvalue())


def upload(bucket: str):
    import boto3
    s3 = boto3.client("s3")
    files = [p for p in OUT.rglob("*") if p.is_file()]
    for p in files:
        s3.upload_file(str(p), bucket, p.relative_to(OUT).as_posix())
    print(f"Uploaded {len(files)} files to s3://{bucket}/raw/")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--starter-dir", required=True, type=Path, help="folder with the starter pack CSVs")
    ap.add_argument("--no-upload", action="store_true")
    args = ap.parse_args()

    print("1/4 Starter pack"); copy_starter(args.starter_dir)
    print("2/4 FRED (Brent, breakeven inflation)"); fetch_fred()
    print("3/4 Prices (VFV, XSP, XESG)"); fetch_prices()
    print("4/4 Holdings (XIU, XESG)"); fetch_holdings()
    write_manifest()

    if not args.no_upload:
        bucket = os.environ.get("BUCKET") or sys.exit("Set BUCKET first: export BUCKET=cascade-s3-bucket")
        upload(bucket)


if __name__ == "__main__":
    main()