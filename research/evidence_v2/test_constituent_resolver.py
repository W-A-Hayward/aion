"""Local integrity/join tests; synthetic PDF bytes are not financial documents.

Temporary test files live only under evidence_v2. The integration case reads the
authorized local inputs if present. No SDK, HTTP client, PDF extraction or pipeline.
"""
import csv
from dataclasses import replace
import io
from pathlib import Path
import tempfile
import unittest

from constituent_resolver import resolve_constituent_evidence
from import_candidates import read_candidates
from research_register import build_register_catalog, read_register_rows
from resolve_xiu import DEFAULT_MANIFEST, ROOT, resolve_local_inputs
from schema import Catalog, Document, EvidencePassage, Verification, ValidationError, digest, document_id, evidence_id
from xiu_holdings import parse_holdings, read_holdings

STAMP = "2026-11-15T13:00:00+00:00"


def sample_holdings(date="Nov 12, 2026", tickers=("ATD", "CNR"), asset_class="Equity", weight="1.46"):
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(["Fund Holdings as of", date])
    writer.writerow(["\u00a0"])
    writer.writerow(["Ticker", "Name", "Sector", "Asset Class", "Weight (%)", "Exchange", "Currency"])
    for t in tickers:
        writer.writerow([t, "SYNTHETIC COMPANY", "Synthetic sector", asset_class,
                         "2.39" if t == "CNR" else weight, "Toronto Stock Exchange", "CAD"])
    writer.writerow(["\u00a0"])
    return out.getvalue().encode("utf-8-sig")


class LocalResolverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix=".resolver-test-", dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.raw = sample_holdings()
        self.snapshot = parse_holdings(self.raw, digest(self.raw))
        self.docs, self.passages, self.paths = [], [], {}
        for ticker in ("ATD.TO", "CNR.TO"):
            raw = b"%PDF-SYNTHETIC TEST BYTES " + ticker.encode()
            sha = digest(raw)
            doc = Document(document_id(sha), sha, "Synthetic issuer", "Synthetic test document",
                           ticker + ".pdf", "en", 2025, "2025-12-31", None, None, False,
                           "not_supplied", Verification(), Verification(), Verification())
            quote = "SYNTHETIC test passage, not a financial fact."
            passage = EvidencePassage(evidence_id(doc.document_id, 1, quote), doc.document_id,
                                      "SYNTHETIC-" + ticker, ticker, "company", 1, "i", "Test",
                                      quote, "operational", "test_only", "unknown", "", False, Verification())
            pdf = self.path / doc.document_file
            pdf.write_bytes(raw)
            self.docs.append(doc)
            self.passages.append(passage)
            self.paths[doc.document_id] = pdf
        self.catalog = Catalog(tuple(self.docs), tuple(self.passages))

    def resolve(self, snapshot=None, catalog=None, **kwargs):
        return resolve_constituent_evidence(snapshot or self.snapshot, catalog or self.catalog,
                                            self.paths, checked_at=STAMP, **kwargs)

    def test_membership_weights_identity_and_statistical_separation(self):
        before = self.catalog.to_bytes()
        result = self.resolve()
        self.assertEqual(result["scope"]["constituent_weight_pct"], 3.85)
        self.assertEqual([p["holding_weight_pct"] for p in result["passages"]], [1.46, 2.39])
        for p in result["passages"]:
            self.assertEqual(p["ticker"], p["subject_ticker"])
            self.assertNotEqual(p["ticker"], "XIU.TO")
            self.assertEqual(p["context"]["association_type"], "holding")
            self.assertEqual(p["context"]["investigation_ticker"], "XIU.TO")
            self.assertEqual(p["context"]["holdings_source_id"], self.snapshot.source_id)
            self.assertEqual(p["stock_return_direction"], "unknown")
            self.assertEqual(p["verification"]["document_bytes"], "verified")
            self.assertEqual(p["verification"]["quote"]["status"], "unverified")
        self.assertIsNone(result["statistical_relationships"]["beta"])
        self.assertEqual(self.catalog.to_bytes(), before)
        self.assertEqual(self.resolve(), result)  # deterministic IDs/order, fixed timestamp

    def test_missing_holdings_file(self):
        with self.assertRaisesRegex(ValidationError, "missing or unreadable"):
            read_holdings(self.path / "missing.csv")

    def test_missing_constituent(self):
        raw = sample_holdings(tickers=("ATD",))
        with self.assertRaisesRegex(ValidationError, "missing or ambiguous"):
            self.resolve(parse_holdings(raw, digest(raw)))

    def test_empty_holdings(self):
        raw = sample_holdings(tickers=())
        with self.assertRaisesRegex(ValidationError, "empty"):
            parse_holdings(raw, digest(raw))

    def test_incorrect_official_date_even_when_bytes_are_pinned(self):
        raw = sample_holdings(date="Nov 15, 2026")
        with self.assertRaisesRegex(ValidationError, "Incorrect official holdings date"):
            parse_holdings(raw, digest(raw))

    def test_resolver_rejects_wrong_snapshot_date_or_etf(self):
        for snapshot in (replace(self.snapshot, as_of="2026-11-15"),
                         replace(self.snapshot, investigation_ticker="XESG.TO")):
            with self.subTest(snapshot=snapshot), self.assertRaises(ValidationError):
                self.resolve(snapshot)

    def test_holdings_hash_mismatch(self):
        with self.assertRaisesRegex(ValidationError, "hash mismatch"):
            parse_holdings(self.raw, "0" * 64)

    def test_unknown_ticker_is_not_guessed(self):
        with self.assertRaisesRegex(ValidationError, "Unmatched constituent"):
            self.resolve(constituents=("CP.TO",))

    def test_duplicate_ticker_is_ambiguous(self):
        raw = sample_holdings(tickers=("ATD", "ATD", "CNR"))
        with self.assertRaisesRegex(ValidationError, "ambiguous"):
            self.resolve(parse_holdings(raw, digest(raw)))

    def test_cash_cannot_be_joined_as_a_company(self):
        raw = sample_holdings(asset_class="Cash")
        with self.assertRaisesRegex(ValidationError, "reviewed CAD TSX equity"):
            self.resolve(parse_holdings(raw, digest(raw)))

    def test_nan_weight_is_rejected(self):
        raw = sample_holdings(weight="NaN")
        with self.assertRaisesRegex(ValidationError, "weight"):
            parse_holdings(raw, digest(raw))

    def test_tampered_document_aborts_all_results(self):
        self.paths[self.docs[1].document_id].write_bytes(b"%PDF-changed")
        with self.assertRaisesRegex(ValidationError, "document hash mismatch"):
            self.resolve()

    def test_swapped_source_documents_are_rejected(self):
        self.paths[self.docs[0].document_id] = self.paths[self.docs[1].document_id]
        with self.assertRaisesRegex(ValidationError, "document hash mismatch"):
            self.resolve()

    def test_missing_document(self):
        self.paths[self.docs[0].document_id] = self.path / "absent.pdf"
        with self.assertRaisesRegex(ValidationError, "PDF missing"):
            self.resolve()

    def test_missing_constituent_evidence_is_not_substituted(self):
        with self.assertRaisesRegex(ValidationError, "Constituent evidence missing"):
            self.resolve(catalog=Catalog(tuple(self.docs), tuple(self.passages[:1])))

    def test_operational_evidence_cannot_be_given_a_stock_direction(self):
        changed = replace(self.passages[0], stock_return_direction="positive")
        with self.assertRaises(ValidationError):
            self.resolve(catalog=Catalog(tuple(self.docs), (changed, self.passages[1])))

    def test_register_hash_mismatch_before_parsing(self):
        p = self.path / "synthetic.xlsx"
        p.write_bytes(b"not a workbook")
        with self.assertRaisesRegex(ValidationError, "register hash mismatch"):
            read_register_rows(p, "0" * 64)

    def test_register_rejects_unknown_ticker_or_receipt_hash(self):
        with self.assertRaisesRegex(ValidationError, "Unmatched evidence ticker"):
            build_register_catalog([{"Ticker": "XIU.TO"}], "a" * 64, {}, "b" * 64, self.path)
        row = {"Ticker": "ATD.TO", "SHA256": "a" * 64}
        receipt = {"entries": [{"id": "ATD_2026_FR", "ticker": "ATD.TO", "sha256": "b" * 64}]}
        with self.assertRaisesRegex(ValidationError, "Document-hash"):
            build_register_catalog([row], "a" * 64, receipt, "b" * 64, self.path)


class SuppliedInputsIntegrationTests(unittest.TestCase):
    def test_twelve_real_candidates_preserve_sources_and_exact_quotes(self):
        holdings = Path.home() / "Downloads/xiu_holdings.csv"
        register = Path.home() / "Downloads/RIPPLE_Official_Research_Register_2026-11-15.xlsx"
        if not all(p.exists() for p in (holdings, register, DEFAULT_MANIFEST)):
            self.skipTest("Authorized local inputs not present; run on the research workstation")
        result = resolve_local_inputs(holdings, register)
        rows, _ = read_register_rows(register)
        source = {r["Research ID"]: r for r in rows}
        self.assertEqual(result["scope"]["passage_count"], 12)
        self.assertEqual(result["scope"]["document_count"], 2)
        self.assertEqual(result["holdings_snapshot"]["row_count"], 65)
        self.assertEqual(result["holdings_snapshot"]["total_displayed_weight_pct"], 100.02)
        self.assertEqual([len([p for p in result["passages"] if p["ticker"] == t])
                          for t in ("ATD.TO", "CNR.TO")], [5, 7])
        for p in result["passages"]:
            row = source[p["research_id"]]
            self.assertEqual(p["excerpt_original"], row["Exact excerpt"])
            self.assertEqual(p["pdf_page"], int(row["PDF page"]))
            self.assertEqual(p["printed_page"], row["Printed page"])
            self.assertEqual(p["document_sha256"], row["SHA256"])
            self.assertEqual(p["quote_verification"]["status"], "reported_verified")
        original = read_candidates(ROOT / "fixtures/atd_candidates.csv").catalog
        self.assertEqual({p.evidence_id for p in original.passages},
                         {p["evidence_id"] for p in result["passages"] if p["ticker"] == "ATD.TO"})


if __name__ == "__main__":
    unittest.main()
