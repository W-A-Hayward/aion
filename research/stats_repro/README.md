# Read-only reproduction of the Brent betas (Phase 2) and CP.TO coverage (Phase 3)

Isolated research workspace. Nothing here modifies `compute/`, `docs/`, the notebook, S3 or any dataset.

| File | Purpose |
|---|---|
| `brent_betas.py` | Runner: imports `compute.stats` unchanged and calls `load_raw` → `build_weekly` → `sensitivities`. `write_outputs` and the S3 client are disabled in-process and restored afterwards. Output: JSON with results, input hashes and code revision. |
| `readonly_store.py` | The two stores `load_raw` can read through: a local folder mirroring `s3://…/raw/`, or a wrapper around a real S3 client. Both allow only `list_objects_v2` and `get_object`, and hash every object read. |
| `test_brent_betas.py` | 8 tests on synthetic raw files: known betas recovered, inputs hashed, writes impossible, missing files named, legacy kept as comparison only, CP.TO candidate handled. |

## Phase 2 status: blocked locally, runner ready

The verified inputs are **not on this machine**. `load_raw` needs these objects; none exist locally (`data/` holds
only evidence documents, and `~/Downloads` has no market data):

| Required object (bucket `cascade-s3-bucket`) | Source per data contract |
|---|---|
| `raw/starter/prices_daily.csv` | Organizer starter pack (31 tickers; includes RY.TO, CNQ.TO, ATD.TO, CNR.TO, XIU.TO, XOM, SPY) |
| `raw/starter/fx_usdcad_daily.csv` | Starter pack (Bank of Canada FXUSDCAD) |
| `raw/starter/macro_rates.csv` | Starter pack (DGS10, DGS2, BD.CDN.10YR/2YR) |
| `raw/prices/snapshot=<latest>/prices_daily_extra.csv` | yfinance via `ingest/fetch_to_s3.py` |
| `raw/fred/snapshot=<latest>/DCOILBRENTEU.csv` | FRED |
| `raw/fred/snapshot=<latest>/T10YIE.csv` | FRED |

So **no beta has been recomputed yet**. The only numbers available are the legacy saved displays in
`compute/run_stats.ipynb` (cell 9), which the runner parses for comparison only:

| Ticker | Legacy beta | Legacy 95% range | Legacy p | n | Legacy reading |
|---|---|---|---|---|---|
| RY.TO | −0.020245 | −0.059567 to 0.019077 | 0.313 | 261 | not significant |
| CNQ.TO | 0.444992 | 0.347390 to 0.542593 | 4.0×10⁻¹⁹ | 261 | significant |
| ATD.TO | −0.074101 | −0.137102 to −0.011100 | 0.021 | 261 | significant at 5% (q = 0.067 across the universe) |
| CNR.TO | −0.016434 | −0.075151 to 0.042283 | 0.583 | 261 | not significant |

These come from an older code version, at an unknown run date and at display precision. Never relabel them as
recomputed.

### SageMaker procedure (backend owner, read-only)

Do **not** run the notebook's publishing cells (`write_outputs`). This procedure reads S3 and writes nothing to it.

1. Open the existing SageMaker notebook instance (its role already reads `cascade-s3-bucket`). Start a terminal.
2. `git clone` the repo, or pull it, and check out the reviewed revision. Note the commit:
   `git rev-parse HEAD` (the runner records it, together with the SHA-256 of `compute/stats.py`).
3. `pip install -r requirements.txt` (pandas, numpy, statsmodels, pyarrow, boto3).
4. Run:
   ```sh
   python research/stats_repro/brent_betas.py --s3-read-only --bucket cascade-s3-bucket \
       --out results/brent_betas_$(date -u +%Y%m%dT%H%M%SZ).json
   ```
   The read-only wrapper forwards only `get_object` and `list_objects_v2`; any other S3 call raises.
5. Check the JSON for each of RY.TO, CNQ.TO, ATD.TO and CNR.TO: `status: computed_now`, beta / 95% range / p / n,
   sample first and last week, method (HAC(4), market control XIU.TO), `inputs_read` (SHA-256 of all 6 objects),
   `code_revision`, `legacy_comparison` (difference, same sign, same significance) and `significance`.
6. Return the JSON file. It is the reproduction record; nothing else is needed.

To run on a laptop instead, copy the six objects into `<dir>/raw/…` with the same keys and use `--raw-dir <dir>`.

## Phase 3: CP.TO

### Data availability

CP.TO price history is **not in the available data**. It is not in the starter pack (the contract's 31-ticker list),
not in `NEW_TICKERS` of `ingest/fetch_to_s3.py`, and not in `UNIVERSE` in `compute/stats.py`. So no local
regression is possible, and none was run.

### Minimal additive proposal (needs teammate approval; NOT applied)

```diff
# ingest/fetch_to_s3.py
-NEW_TICKERS = ["VFV.TO", "XSP.TO", "XESG.TO", "XRB.TO", "XLB.TO", "XEG.TO"]
+NEW_TICKERS = ["VFV.TO", "XSP.TO", "XESG.TO", "XRB.TO", "XLB.TO", "XEG.TO", "CP.TO"]

# compute/stats.py  (extra universe; market control follows the existing rule: .TO stock -> XIU.TO)
-    "XRB.TO", "XLB.TO", "XEG.TO",
+    "XRB.TO", "XLB.TO", "XEG.TO", "CP.TO",

# compute/test_stats.py
-    assert len(stats.EXTRA_TICKERS) == 21
-    assert len(set(stats.UNIVERSE)) == 35
-    assert stats.EXTRA_TICKERS[-3:] == ["XRB.TO", "XLB.TO", "XEG.TO"]
+    assert len(stats.EXTRA_TICKERS) == 22
+    assert len(set(stats.UNIVERSE)) == 36
+    assert stats.EXTRA_TICKERS[-4:] == ["XRB.TO", "XLB.TO", "XEG.TO", "CP.TO"]

# docs/data_contract.md
- Extra tickers (21, universe = "extra"): ... XRB.TO XLB.TO XEG.TO (from prices_daily_extra.csv)
+ Extra tickers (22, universe = "extra"): ... XRB.TO XLB.TO XEG.TO CP.TO (from prices_daily_extra.csv)
- Universe = core + extra = 35 tickers.
+ Universe = core + extra = 36 tickers.
```

Also check: `lambdas/tools/app.py` `EXTRA`, the agent's tool docstrings and `prompts/action_group_functions.md`
list the allowed tickers, so they need the same addition for the agent to accept CP.TO. `MAIN_CHANNEL` in
`compute/evidence.py` would default CP.TO to "none" unless a channel is added (for example "company-specific").

**Multiple testing:** `q_simple` is Benjamini-Hochberg across the whole universe. Adding a 36th ticker changes every
ticker's q-value, and with it the extra-universe green/yellow labels (which need q < 0.10). Recompute all of them in
the same run; do not patch CP.TO into an old table.

### Validation checklist for CP.TO data (before trusting any beta)

| Check | How | Expected / to verify |
|---|---|---|
| Identity | yfinance `CP.TO` metadata; TSX listing | Canadian Pacific Kansas City Limited, TSX "CP". **To verify:** the company was renamed from Canadian Pacific Railway in 2023 after the KCS combination; the ticker and listing should be continuous. Do not use NYSE "CP" (USD). |
| Currency | `currency` column | CAD (TSX). No FX conversion, like other .TO tickers. |
| Adjusted prices | `adj_close` with `auto_adjust=False`, as the pipeline already does | **To verify:** any split before the sample start (one is believed to be in 2021) must be reflected in adj_close; check for a single-day jump above 50%. |
| Date coverage | first/last date | Must span 2021-11-19 to the latest week like the others; build_weekly needs ≥ 150 weekly returns. |
| Continuity / missing | count trading days per week; list weeks with no price | Report the count; build_weekly takes the last available price per W-FRI week, so isolated gaps are absorbed, but a long gap is a red flag. |
| Duplicates | `(date, ticker)` duplicates | build_weekly keeps the last; there should be none. |

Then run: `brent_betas.py --s3-read-only --candidate-ticker CP.TO` (appends CP.TO in memory only, labels the q-values
as enlarged-universe).

## Running the tests

```sh
cd research/stats_repro && python -m pytest -q          # needs pandas, numpy, statsmodels
```

## Note for the backend owner

`build_weekly` fails with a TypeError if `prices_daily_extra.csv` has a header but no rows: pandas reads the empty
columns as text and `np.log` cannot apply. This was found while writing the tests. It is not a problem with the
current data, but it is worth a guard in `compute/stats.py`. Not changed here.
