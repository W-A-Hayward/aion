"""Strict, local parsing of the supplied dated XIU CSV. No inferred memberships."""
import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import io
from pathlib import Path

from schema import ValidationError, canonical_bytes, digest, require

XIU_DATE = "2026-11-12"
XIU_SHA256 = "9caae3aa6b3aa4ad4faf2b37c9f96fd604f2a10c8cb60831f388ad0a28947527"
# Explicit reviewed exchange-qualified aliases, not a general suffix heuristic.
ALIASES = {"ATD.TO": "ATD", "CNR.TO": "CNR"}
REQUIRED = {"Ticker", "Name", "Sector", "Asset Class", "Weight (%)", "Exchange", "Currency"}


@dataclass(frozen=True)
class Holding:
    source_row: int
    row_id: str
    ticker_original: str
    company_name: str
    sector: str
    asset_class: str
    weight_pct: Decimal
    exchange: str
    currency: str


@dataclass(frozen=True)
class HoldingsSnapshot:
    investigation_ticker: str
    as_of: str
    sha256: str
    source_id: str
    rows: tuple[Holding, ...]


def read_holdings(path, expected_sha256=XIU_SHA256, expected_date=XIU_DATE):
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise ValidationError("Holdings file missing or unreadable; no fallback membership") from exc
    return parse_holdings(raw, expected_sha256, expected_date)


def parse_holdings(raw, expected_sha256, expected_date=XIU_DATE):
    require(digest(raw) == expected_sha256, "Holdings source hash mismatch")
    try:
        records = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True))
        dates = [r[1] for r in records if len(r) == 2 and r[0] == "Fund Holdings as of"]
        require(len(dates) == 1, "Exactly one official holdings date is required")
        month, day, year = dates[0].replace(",", "").split()
        months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
        as_of = date(int(year), months.index(month) + 1, int(day)).isoformat()
        require(as_of == expected_date, "Incorrect official holdings date")
        headers = [(i, r) for i, r in enumerate(records) if r and r[0] == "Ticker"]
        require(len(headers) == 1, "Exactly one holdings table is required")
        start, header = headers[0]
        require(len(header) == len(set(header)) and REQUIRED <= set(header), "Invalid holdings columns")
        holdings = []
        for index, values in enumerate(records[start + 1:], start=start + 2):
            if not any(v.strip() for v in values):
                continue  # Blank/NBSP rows only, not arbitrary unparsed footers.
            require(len(values) == len(header), "Malformed holdings row")
            row = dict(zip(header, values))
            require(all(row[k].strip() for k in REQUIRED), "Missing holding field")
            weight = Decimal(row["Weight (%)"])
            require(weight.is_finite() and 0 <= weight <= 100, "Invalid holding weight")
            identity = "holding:sha256:" + digest(canonical_bytes([expected_sha256, index, values]))
            holdings.append(Holding(index, identity, row["Ticker"], row["Name"], row["Sector"],
                                    row["Asset Class"], weight, row["Exchange"], row["Currency"]))
        require(bool(holdings), "Holdings table is empty")
        return HoldingsSnapshot("XIU.TO", as_of, expected_sha256,
                                "holdings:sha256:" + expected_sha256, tuple(holdings))
    except (csv.Error, UnicodeError, ValueError, InvalidOperation) as exc:
        raise ValidationError(f"Invalid holdings snapshot: {exc}") from exc


def confirmed_holding(snapshot, ticker):
    require(ticker in ALIASES, "Unmatched constituent ticker; no automatic alias inference")
    matches = [r for r in snapshot.rows if r.ticker_original == ALIASES[ticker]]
    require(len(matches) == 1, "Required constituent missing or ambiguous in holdings")
    row = matches[0]
    require(row.asset_class == "Equity" and row.exchange == "Toronto Stock Exchange"
            and row.currency == "CAD", "Holding is not the reviewed CAD TSX equity")
    return row
