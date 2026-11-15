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
                                   tickers VFV.TO XSP.TO XESG.TO XRB.TO XLB.TO XEG.TO, currency CAD
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
  Personas and alternatives only use these core tickers (universe = "core").
Extra tickers (21, universe = "extra"):
  CNQ.TO CNR.TO FTS.TO TD.TO MFC.TO CSU.TO NVDA AAPL MSFT GOOGL AMZN TSLA JPM JNJ PG GLD AGG ESGV
    (18 from prices_daily.csv)
  XRB.TO XLB.TO XEG.TO (from prices_daily_extra.csv)
Universe = core + extra = 35 tickers. BTC-USD and ETH-USD are in prices_daily.csv but are never used.
A ticker with fewer than 150 weekly returns is skipped with a printed warning.
Market control: SPY for US stocks; XIU.TO for .TO stocks; none (simple values copied, market_ticker = "none")
  for ETFs that are not single stocks: XIU.TO, XESG.TO, SPY, VFV.TO, XSP.TO, GLD, AGG, ESGV, XRB.TO, XLB.TO, XEG.TO.
  Bond ETFs XBB.TO, ZST.TO and TLT keep the market control (XIU.TO for the .TO funds, SPY for TLT).
Oil factor: weekly log return of Brent (USD). Weeks end Friday (W-FRI), last available close.
All asset returns: weekly log returns of adj_close, also converted to CAD with FX
  (USD tickers: ret_cad = ret_local + weekly log change of usdcad).
Sample: 2021-11-19 to latest. Out-of-sample: estimate on weeks <= 2024-12-31, test on weeks >= 2025-01-01.
Regressions: OLS with Newey-West (HAC, 4 lags) standard errors; 95% ranges = beta +/- 1.96*se.

summary.md also reports a diagnostic: beta of (VFV.TO - XSP.TO) weekly log return on the weekly log change of
usdcad with its 95% range; expected near +1, a warning is printed (and written) if outside 0.5..1.5.

Durations (effective, years), from issuer documents in raw/manual_docs/ (yield link: TLT oil>us10y, XBB.TO oil>ca10y,
ZST.TO oil>ca2y):
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
                 beta_up, beta_down, oos_hit_rate, oos_n, n_weeks, q_simple, universe
                 (one row per ticker in the universe; q_simple = Benjamini-Hochberg adjusted p_simple across
                 all tickers, p_simple itself is unchanged; universe = core | extra)
  rolling: ticker, week, beta_52w, universe
  links: link_id, from_node, to_node, beta, lo, hi, p, unit   (e.g. oil>us10y, us10y>TLT, oil>usdcad, oil>breakeven,
                 oil>ca2y, ca2y>ZST.TO, ca10y>XLB.TO, ca10y>XRB.TO; ca10y>XRB.TO is information only, no chain)
  chain_reconciliation: ticker, chain, beta_direct, beta_chain, share_explained
                 (chains for TLT, XBB.TO, ZST.TO (oil>ca2y>ZST.TO, Canada 2y), VFV.TO, QQQ, SHOP.TO,
                 XLB.TO oil>ca10y>XLB.TO; no chain for XRB.TO: nominal yields do not price real return bonds)
  duration_check: ticker, duration_years, yield_move_per_10pct_oil_bp, implied_move_pct, measured_move_pct
  persona_holdings: persona, ticker, weight
  portfolio_exposure: persona, ticker, weight, beta, lo, hi, contribution   (per-holding contributions)
  portfolio_beta: persona, beta, lo, hi, p, r2, n_weeks   (one row per persona; weekly portfolio return
                 = log(1 + sum(weight * (exp(ret_cad) - 1))): weighted simple returns
                 summed, then logged; regressed on Brent with the same HAC(4) OLS)
  scenarios: subject, subject_type (persona|ticker), shock_pct, impact_pct, lo_pct, hi_pct
                 (persona rows use the portfolio_beta beta and range)
  alternatives: persona, holding, alternative, beta_holding, beta_alternative, impact30_before_pct, impact30_after_pct
  evidence: evidence_id, ticker, doc_type, channel, direction, source_url, section, excerpt, s3_key
  confidence: ticker, channel, label, reason_code, reason_text
  edges: from_node, to_node, edge_type, beta, lo, hi, evidence_id
  weekly_returns: week, subject_or_ticker, ret_cad, brent_ret
                 (long format; the weekly series used by the five tables below, one row per ticker or subject
                 and week; ret_cad is a log return, brent_ret the Brent log return of the same week)
  risk_share: subject, subject_type, factor, beta, lo, hi, p, r2, n_weeks
                 (subject_type persona | alternative; factor oil | rates | stocks, each a SEPARATE single-factor
                 HAC(4) regression of the subject's weekly return: oil = Brent log return, rates = weekly change
                 of BD.CDN.10YR.DQ.YLD in pp, stocks = XIU.TO ret_cad. r2 = share of the subject's weekly
                 variance explained by that factor alone. The three r2 values overlap (the factors move
                 together) and do NOT add up.)
  stress_history: subject, subject_type, window_weeks, direction, threshold_pct, n_episodes, avg_oil_move_pct,
                 avg_return_pct, worst_return_pct, worst_end_date, per_100k_avg, per_100k_worst,
                 episode_end_dates, regimes
                 (window_weeks 1 | 4 | 13; direction oil_up | oil_down. Window 1: top 10% of weeks by Brent log
                 return (bottom 10% for oil_down), plus threshold_pct 5 and 20. Windows 4 and 13: rolling sums
                 of log returns, largest Brent windows picked greedily and NON-OVERLAPPING, up to 10 (4 weeks)
                 and 5 (13 weeks) episodes, threshold_pct null. Returns are simple returns in percent;
                 per_100k_* = return_pct * 1000. episode_end_dates and regimes are comma lists (regimes =
                 distinct calendar years of the episode end dates). Descriptive only ("realized returns in past
                 large oil moves"): no p-values or confidence intervals, episodes are not independent.)
  stress_contributions: persona, ticker, weight, window_weeks, direction, avg_return_pct, contribution_pct,
                 share_of_loss
                 (personas only, window 1 uses the 10% threshold; contribution_pct = weight * avg_return_pct;
                 share_of_loss = contribution / sum of the persona's contributions. The sum equals the
                 persona's avg_return_pct in stress_history for window 1 and is within 0.5 pp for 4 and 13 weeks.)
  materiality: subject, subject_type, verdict, verdict_at_5, verdict_at_15, oil_r2, oil_p, stress13_avg_pct,
                 normal_swing13_pct, n_episodes_13, regimes, reason_text
                 (oil_r2, oil_p = the subject's oil row in risk_share; stress13_avg_pct, n_episodes_13, regimes =
                 the oil_up 13-week row in stress_history; normal_swing13_pct = standard deviation, in percent,
                 of the subject's NON-OVERLAPPING 13-week simple returns (consecutive blocks from the first week).)
Subjects (risk tables): the 3 personas (subject_type persona) and each alternative (subject_type alternative,
  subject "<persona>:<holding>-><alternative>", e.g. "robert:TLT->ZST.TO", weights after the swap).
  Weekly subject return = log(1 + sum(weight * (exp(ret_cad) - 1))).
Materiality rule (constants at the top of compute/stats.py, fixed before looking at results; OIL_R2_MATERIAL = 0.10):
  "not linked"           if oil_p >= 0.05;
  "material"             if oil_r2 >= OIL_R2_MATERIAL OR |stress13_avg_pct| > normal_swing13_pct;
  "measurable but minor" otherwise.
  verdict_at_5 / verdict_at_15 apply the same rule with OIL_R2_MATERIAL = 0.05 / 0.15.
channel values: direct | rates | currency | company-specific | none
label rules: green = p_simple<0.05 AND p_ex2022<0.05 with the same sign AND (share_explained>=0.5 OR an evidence row
             with the same direction); yellow = p_simple<0.05 but the rest fails; grey = p_simple>=0.05.
             For universe = extra, green/yellow also require q_simple<0.10, otherwise grey.

AWS names: region us-east-1; Glue database cascade; Athena workgroup cascade; DynamoDB table cascade-jobs
(key jobId, TTL expiresAt); SQS agent-jobs + agent-jobs-dlq; Lambdas cascade-tools|submit|worker|status;
roles cascade-<name>-lambda; agent cascade-agent, alias live; KB cascade-evidence; guardrail cascade-guardrail.
```