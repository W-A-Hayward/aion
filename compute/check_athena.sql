-- Recompute beta_simple with regr_slope in Athena and compare it with the sensitivities table.
-- Run by compute/check_athena.py (workgroup cascade, database cascade). Each statement starts with a
-- "-- name: <name>" line; the script reads statements by name. You can also paste them in the Athena console.
--
-- weekly_returns: written by compute/stats.py (weekly_returns_table) to processed/weekly_returns/, one row
-- per week and ticker (or persona): ret_cad is the weekly log return in CAD, brent_ret the weekly log
-- return of Brent (USD). compute/check_athena.py writes it from stats.py if the folder is empty.

-- name: create_weekly_returns
CREATE EXTERNAL TABLE IF NOT EXISTS cascade.weekly_returns (
  week date,
  subject_or_ticker string,
  ret_cad double,
  brent_ret double
)
STORED AS PARQUET
LOCATION 's3://cascade-s3-bucket/processed/weekly_returns/';

-- name: recompute_beta_simple
-- regr_slope(y, x) is the OLS slope of y on x over the rows where both are not null, the same
-- estimate as beta_simple (the HAC errors change the standard errors, not the slope).
SELECT
  subject_or_ticker AS ticker,
  regr_slope(ret_cad, brent_ret) AS beta_recomputed,
  count(*) AS n_weeks
FROM cascade.weekly_returns
WHERE subject_or_ticker IN ('XOM', 'TLT', 'ENB.TO', 'QQQ', 'RY.TO')
  AND ret_cad IS NOT NULL
  AND brent_ret IS NOT NULL
GROUP BY subject_or_ticker
ORDER BY subject_or_ticker;

-- name: stored_beta_simple
SELECT ticker, beta_simple, n_weeks
FROM cascade.sensitivities
WHERE ticker IN ('XOM', 'TLT', 'ENB.TO', 'QQQ', 'RY.TO')
ORDER BY ticker;
