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
                                   DGS10 (US 10y), DGS2 (US 2y); values in percent;
                                   CPIAUCSL (US CPI index, monthly, dated the 1st of the month) is used only by stock_bond
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
  facts: subject, subject_type, max_drawdown_pct, drawdown_peak_date, drawdown_trough_date, recovery_date,
                 worst_year, worst_year_return_pct, worst_13w_return_pct, worst_13w_end_date, total_return_pct,
                 annualized_volatility_pct, n_weeks, dd_us10y_chg_pp, dd_ca10y_chg_pp, dd_brent_chg_pct,
                 dd_xiu_chg_pct, w13_us10y_chg_pp, w13_ca10y_chg_pp, w13_brent_chg_pct, w13_xiu_chg_pct
                 (one row per subject: the 3 personas and the alternatives. Weekly CAD SIMPLE returns, wealth
                 starts at 1.0 the Friday before the first week. max_drawdown_pct <= 0, in percent; peak =
                 first date the peak level was reached (may be that starting Friday); recovery_date = first
                 later date at or above the peak, null if not recovered. worst_year = lowest compounded return
                 among FULL calendar years only (week data from Jan 7 or earlier to Dec 25 or later; the first
                 and the current partial year are excluded). worst_13w = lowest compounded return over 13
                 consecutive weeks, dated by its last week. annualized_volatility_pct = std of weekly simple
                 returns (ddof 1) * sqrt(52) * 100. Context columns: dd_* over the weeks after the peak date up
                 to the trough date, w13_* over the 13 weeks of the worst 13 weeks; yields = sum of weekly
                 changes in pp (DGS10 us10y, BD.CDN.10YR.DQ.YLD ca10y), Brent and XIU.TO = compounded change
                 in percent (XIU.TO in CAD); null if a week is missing or there is no drawdown.
                 Weeks without a Brent return are not in the weekly series, so their returns are not compounded.)
  protection: subject, subject_type (persona|pair), stock_side, bond_side, period, n_weeks, avg_bond_return_pct,
                 avg_stock_return_pct, n_worst_weeks
                 (subjects: robert (the only persona with a bond fund; stock side = its non-bond holdings ENB.TO
                 and RY.TO, bond side = TLT and XBB.TO, each side weighted by the persona weights rescaled to 1),
                 and the pairs XIU.TO/XBB.TO and SPY/TLT (stock/bond). Bond funds: TLT, XBB.TO, ZST.TO. The worst
                 weeks are the bottom 10% of all weeks for the stock side (count rounded up, ties by earlier
                 date; n_worst_weeks). period = 2022 (calendar year 2022) | 2026_ytd (calendar year 2026) |
                 other | all (a pooled row per subject over all worst weeks, n_weeks = n_worst_weeks);
                 n_weeks per period (excluding all) sums to n_worst_weeks; avg_bond_return_pct = mean weekly simple
                 return of the bond side in those weeks, in percent; null if n_weeks = 0.)
  stock_bond: pair, measure, week, correlation, n_weeks, regime, z_diff, p_diff
                 (pairs XIU.TO/XBB.TO and SPY/TLT, weekly CAD simple returns. measure rolling_52w: one row per
                 week with a full 52-week window, n_weeks = 52. measure cpi_ge_3 / cpi_lt_3: full-sample
                 correlation (week null) in weeks where US CPI year-over-year is >= 3.0% / < 3.0%; n_weeks =
                 weeks used. CPI year-over-year = CPIAUCSL / value 12 months earlier - 1, each month's value
                 forward-filled onto the weeks from its dated 1st of the month; weeks before the first
                 year-over-year value (2022-11-01 with data from 2021-11) belong to neither regime.
                 regime = "US CPI" on the cpi_ge_3 / cpi_lt_3 rows, null on rolling_52w. z_diff, p_diff = Fisher
                 z test of corr(CPI>=3) vs corr(CPI<3) for the pair (two-sided p), the same values on both
                 regime rows, null on rolling rows and when a sample has 3 weeks or fewer. It assumes
                 independent weeks; high-CPI weeks are mostly one 2021-2023 block.)
  comovement: persona, scope, avg_pairwise_corr, n_pairs, n_weeks
                 (scope all | worst_10pct; mean of the pairwise correlations of the persona's holdings, weekly
                 CAD simple returns; worst_10pct = the 10% worst weeks for the persona's portfolio return
                 (count rounded up); n_pairs = pairs of holdings; n_weeks = weeks used. The worst_10pct rows
                 stay in the table but are not printed in summary.md.)
  shields: persona, item, label, avg_pct_worst, weeks_up, weeks, binom_p, usd_weight, contribution_pct,
                 contribution_per_100k, twin_max_drawdown, actual_max_drawdown
                 (per persona, in the persona's own worst 10% portfolio weeks (count rounded up, ties by earlier
                 date), weekly CAD simple returns. EXTERNAL items only, no row for the persona's own holdings
                 (they are tautologically BROKEN): usdcad (weekly change), then GLD, ZST.TO, XBB.TO, AGG,
                 TLT_usd (TLT minus usdcad), then the hedged twin "<persona>:A->B" when a hedged swap exists
                 (mateo:VFV.TO->XSP.TO). An item is skipped when the persona holds it (so XBB.TO and TLT_usd
                 have no row for robert) or when its ticker has no returns (warning printed).
                 avg_pct_worst = mean return in percent; weeks_up = weeks with return > 0; weeks = weeks with
                 data; binom_p = exact two-sided binomial p of weeks_up vs 0.5. usd_weight = weight of holdings
                 priced in USD or CAD-listed with unhedged USD exposure (VFV.TO); filled on the usdcad and twin
                 rows only. contribution_pct is in percentage points: usdcad row = usd_weight * avg usdcad
                 change in those weeks; twin row = actual portfolio avg_pct_worst minus twin avg_pct_worst (the
                 cushion the swap would remove, positive if the twin did worse). contribution_per_100k =
                 contribution_pct * 1000. twin_max_drawdown and actual_max_drawdown (percent, full sample) are
                 filled on the twin row only. label: WORKING (avg_pct_worst > 0 and weeks_up/weeks >= 0.6 and
                 binom_p < 0.10), BROKEN (avg_pct_worst <= 0), HIDDEN (usdcad row meeting the WORKING rules
                 with usd_weight > 0), REMOVED (twin max drawdown deeper than the actual), else NEUTRAL
                 (inconclusive). Descriptive: 2021-2026 only, past behaviour.)
  shield_by_crash_type: threshold_set, shield, crash_type, n_weeks, avg_pct, weeks_up, binom_p
                 (market-level, all weeks with an XIU.TO return, not per persona. crash_type: stock_crash =
                 XIU.TO weekly CAD simple return < the stock cut-off (%); rate_shock = US 10y weekly change >
                 the rate cut-off (bp) AND XIU.TO >= the stock cut-off; other = the rest (a week with no US 10y
                 change cannot be a rate shock). threshold_set = "<stock %>/<rate bp>": "-2/+10" (base),
                 "-1.5/+5", "-2.5/+15". shield: usdcad, GLD, ZST.TO, XBB.TO, AGG, TLT_usd (a shield without
                 returns has no rows; a crash type with no weeks keeps its row with n_weeks 0 and null
                 avg_pct, binom_p). avg_pct = mean weekly simple return in percent; weeks_up = weeks with
                 return > 0; binom_p = exact two-sided binomial p vs 0.5. Written by
                 stats.build_shield_by_crash_type(); descriptive, 2021-2026 only, past behaviour,
                 thresholds tested at three levels.)
  cushion: stock_side, candidate, avg_pct_worst, weeks_up, weeks, binom_p, avg_pct_all, corr_full
                 (stock_side XIU.TO | SPY, over the stock side's worst 10% weeks (count rounded up, ties by
                 earlier date). candidate: usdcad (weekly change), TLT_usd (TLT minus usdcad) and every
                 universe ticker with returns except the stock side itself; weekly simple returns.
                 avg_pct_worst / avg_pct_all = mean return in percent in the worst weeks / all weeks;
                 weeks_up = worst weeks with return > 0; weeks = worst weeks with data; binom_p = exact
                 two-sided binomial p vs 0.5; corr_full = full-sample correlation with the stock side.
                 Descriptive, 2021-2026 only, past behaviour.)
  crash_profile: persona, n_weeks, avg_xiu_pct, avg_us10y_chg_bp, avg_ca10y_chg_bp, avg_brent_pct,
                 stock_crash_share, rate_shock_share, crash_type
                 (one row per persona, over the persona's own worst 10% portfolio weeks (same weeks as shields);
                 n_weeks = their number. avg_xiu_pct = mean XIU.TO weekly CAD simple return in percent;
                 avg_us10y_chg_bp / avg_ca10y_chg_bp = mean weekly change of DGS10 / BD.CDN.10YR.DQ.YLD in
                 basis points; avg_brent_pct = mean Brent simple return in percent. stock_crash_share = share
                 of those weeks with XIU.TO < -2%; rate_shock_share = share with US 10y up > 10 bp (each over
                 the weeks that have data). crash_type = "stock" if stock_crash_share >= 0.5, "rates" if
                 rate_shock_share >= 0.5, "mixed" otherwise (also when both are >= 0.5). Written by
                 stats.build_crash_profile(); descriptive, 2021-2026 only, past behaviour.)
Subjects (risk tables): the 3 personas (subject_type persona) and each alternative (subject_type alternative,
  subject "<persona>:<holding>-><alternative>", e.g. "robert:TLT->ZST.TO", weights after the swap).
  Weekly subject return = log(1 + sum(weight * (exp(ret_cad) - 1))).
History constants (top of the history section in compute/stats.py, fixed before looking at results):
  WORST_WEEKS_SHARE = 0.10, CPI_YOY_THRESHOLD_PCT = 3.0, WORST_WINDOW_WEEKS = 13, rolling window 52 weeks.
summary.md also lists the facts, protection, stock_bond and comovement tables in readable form (the context
  columns of facts as a second table), plus shields and crash_profile with the note
  "2021-2026 only; past behaviour; descriptive".
Materiality rule (constants at the top of compute/stats.py, fixed before looking at results; OIL_R2_MATERIAL = 0.10):
  "not linked"           if oil_p >= 0.05;
  "material"             if oil_r2 >= OIL_R2_MATERIAL OR |stress13_avg_pct| > normal_swing13_pct;
  "measurable but minor" otherwise.
  verdict_at_5 / verdict_at_15 apply the same rule with OIL_R2_MATERIAL = 0.05 / 0.15.
channel values: direct | rates | currency | company-specific | none
label rules: green = p_simple<0.05 AND p_ex2022<0.05 with the same sign AND (share_explained>=0.5 OR an evidence row
             with the same direction); yellow = p_simple<0.05 but the rest fails; grey = p_simple>=0.05.
             For universe = extra, green/yellow also require q_simple<0.10, otherwise grey.

Sources
  Data series:
    Bank of Canada USD/CAD (FXUSDCAD)  -> raw/starter/fx_usdcad_daily.csv
    FRED CPIAUCSL (US CPI index)       -> raw/starter/macro_rates.csv, used only by stock_bond
  Research documents (doc_type "research", ticker "macro", topic currency | stock_bond): one row per document
    in raw/manual_docs/manifest_docs.csv, listed here with publisher, topic, URL (copied from the manifest,
    never typed by hand) and trust tier:
    | file | publisher | topic | source_url | trust |
    | bis-stock-bond-correlation-2023-12.html | BIS | stock_bond | https://www.bis.org/publ/qtrpdf/r_qt2312v.htm | Central bank |
    | fed-safe-haven-bonds-2026-10.html | Federal Reserve | stock_bond | https://www.federalreserve.gov/econres/notes/feds-notes/government-bonds-safe-haven-property-and-inflationary-pressures-20261016.html | Central bank |
    | msci_2011_currency_hedging.pdf | MSCI | currency | https://www.msci.com/documents/10199/ecc9a964-0c09-4184-8ba7-084382b8074f | Research |
    | boc_san_2025_2_cad_risk.pdf | Bank of Canada | currency | https://www.bankofcanada.ca/2025/02/staff-analytical-note-2025-2/ | Central bank |
    | boc_mpr_2025_01_infocus.pdf | Bank of Canada | inferred from text | https://www.bankofcanada.ca/publications/mpr/mpr-2025-01-29/in-focus-2/ | Central bank |
    | boc_san_2017_1_cad_commodities.pdf | Bank of Canada | currency | https://www.bankofcanada.ca/wp-content/uploads/2017/02/san2017-1.pdf | Central bank |
    The manifest has no topic column: topics above are read from the file names; the pipeline infers the
    topic from the text when the column is empty (boc_mpr_2025_01_infocus.pdf has no topic in its name).

  Trust tier, from the document's host: Central bank = bis.org, federalreserve.gov, bankofcanada.ca;
    Research = msci.com; Fund issuer = ishares/blackrock, vanguard, bmo; Company filing = annual reports;
    Press = everything else. The evidence table also carries publisher, date ("not stated" if unknown) and trust.


AWS names: region us-east-1; Glue database cascade; Athena workgroup cascade; DynamoDB table cascade-jobs
(key jobId, TTL expiresAt; also holds rate#... rate-limit counters); SQS agent-jobs + agent-jobs-dlq;
Lambdas cascade-tools|research|submit|worker|status; roles cascade-<name>-lambda; AgentCore runtime cascade_agent
with role cascade-agentcore-runtime; HTTP API cascade-api (POST /jobs, GET /jobs/{id}, GET /research?ticker=);
KB cascade-evidence; guardrail cascade-guardrail. Setup steps: docs/infrastructure.md.
Job ownership: header X-Cascade-Session (32-128 chars [A-Za-z0-9_-]) or a JWT sub; jobs store only ownerHash
(SHA-256), and GET /jobs/{id} answers 404 to anyone but the owner.
```