# Data contract — cascade MVP

Every notebook, Lambda and eval script uses these names. Persona weights are demo assumptions.

```text
S3 bucket: cascade-s3-bucket (env var BUCKET=cascade-s3-bucket).
All raw files are CSV. Raw inputs under raw/ (written by ingest/fetch_to_s3.py):
  raw/starter/prices_daily.csv     date,ticker,open,high,low,close,adj_close,volume,currency
                                   (31 tickers, 2021-11-12 to 2026-11-12; currency USD or CAD)
  raw/starter/fx_usdcad_daily.csv  date,usdcad,cadusd   (Bank of Canada FXUSDCAD)
  raw/starter/macro_rates.csv      date,series_id,value,unit,frequency,label,source  (long format)
                                   series used: BD.CDN.10YR.DQ.YLD (CA 10y), BD.CDN.2YR.DQ.YLD (CA 2y),
                                   DGS10 (US 10y), DGS2 (US 2y); values in percent
  raw/prices/snapshot=YYYY-MM-DD/prices_daily_extra.csv  same columns as prices_daily.csv,
                                   tickers VFV.TO XSP.TO XESG.TO, currency CAD
  raw/fred/snapshot=YYYY-MM-DD/DCOILBRENTEU.csv, T10YIE.csv
                                   FRED CSV: two columns, first is the date (header "observation_date"
                                   or "DATE"), second is the value (header = series id); "." or empty = missing
  raw/holdings/snapshot=YYYY-MM-DD/xiu_holdings.csv, xesg_holdings.csv
                                   iShares CSV: a few header rows, then a table starting with "Ticker"
  raw/manual_docs/                 PDFs + manifest_docs.csv (file,ticker,doc_type,source_url)
  raw/manifest.csv                 provenance of every raw file (not read by the pipeline)
Snapshot folders: always use the latest snapshot=YYYY-MM-DD.

MVP tickers (14): XIU.TO ENB.TO XOM TLT XBB.TO ZST.TO QQQ SHOP.TO SPY VFV.TO XSP.TO XESG.TO ATD.TO RY.TO
  (11 from prices_daily.csv; VFV.TO XSP.TO XESG.TO from prices_daily_extra.csv)
Market control: SPY for US tickers; XIU.TO for .TO stock tickers; none for ETFs that are a market
  (XIU.TO, XESG.TO, SPY, VFV.TO, XSP.TO).
Oil factor: weekly log return of Brent (USD). Weeks end Friday (W-FRI), last available close.
All asset returns: weekly log returns of adj_close, also converted to CAD with FX
  (USD tickers: ret_cad = ret_local + weekly log change of usdcad).
Sample: 2021-11-19 to latest. Out-of-sample: estimate on weeks <= 2024-12-31, test on weeks >= 2025-01-01.
Regressions: OLS with Newey-West (HAC, 4 lags) standard errors; 95% ranges = beta +/- 1.96*se.

Durations (effective, years), from issuer documents in raw/manual_docs/:
  TLT 14.63 (fact sheet, 2026-09-30); XBB.TO 6.72 (product page, 2026-10-23); ZST.TO 0.40 (fact sheet, 2026-10-30)

Personas (persona_holdings, weights sum to 1):
  robert: TLT 0.30, XBB.TO 0.40, ENB.TO 0.15, RY.TO 0.15   (low-moderate risk, 3-5 y, advanced)
  amira:  QQQ 0.50, SHOP.TO 0.25, XIU.TO 0.25              (high risk, 15+ y, intermediate)
  mateo:  XIU.TO 0.50, VFV.TO 0.50                         (moderate risk, ESG, 8-12 y, intermediate)
Alternatives: robert TLT->ZST.TO, robert XBB.TO->ZST.TO, mateo XIU.TO->XESG.TO, mateo VFV.TO->XSP.TO,
              amira QQQ->XIU.TO (shift 0.25 of weight)

Processed tables: Parquet, one folder per table: processed/<table>/part-0.parquet
  sensitivities: ticker, beta_simple, lo_simple, hi_simple, p_simple, beta_mkt, lo_mkt, hi_mkt, p_mkt,
                 market_ticker, r2_incremental, exxon_equiv, beta_ex2022, lo_ex2022, hi_ex2022, p_ex2022,
                 beta_up, beta_down, oos_hit_rate, oos_n, n_weeks
  rolling: ticker, week, beta_52w
  links: link_id, from_node, to_node, beta, lo, hi, p, unit   (e.g. oil>us10y, us10y>TLT, oil>usdcad, oil>breakeven)
  chain_reconciliation: ticker, chain, beta_direct, beta_chain, share_explained
  duration_check: ticker, duration_years, yield_move_per_10pct_oil_bp, implied_move_pct, measured_move_pct
  persona_holdings: persona, ticker, weight
  portfolio_exposure: persona, ticker, weight, beta, lo, hi, contribution
  scenarios: subject, subject_type (persona|ticker), shock_pct, impact_pct, lo_pct, hi_pct
  alternatives: persona, holding, alternative, beta_holding, beta_alternative, impact30_before_pct, impact30_after_pct
  evidence: evidence_id, ticker, doc_type, channel, direction, source_url, section, excerpt, s3_key
  confidence: ticker, channel, label, reason_code, reason_text
  edges: from_node, to_node, edge_type, beta, lo, hi, evidence_id
channel values: direct | rates | currency | company-specific | none
label rules: green = p_simple<0.05 AND p_ex2022<0.05 with the same sign AND (share_explained>=0.5 OR an evidence row
             with the same direction); yellow = p_simple<0.05 but the rest fails; grey = p_simple>=0.05.

AWS names: region us-east-1; Glue database cascade; Athena workgroup cascade; DynamoDB table cascade-jobs
(key jobId, TTL expiresAt); SQS agent-jobs + agent-jobs-dlq; Lambdas cascade-tools|submit|worker|status;
roles cascade-<name>-lambda; agent cascade-agent, alias live; KB cascade-evidence; guardrail cascade-guardrail.
```