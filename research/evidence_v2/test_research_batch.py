"""Validate the new research against original LOCAL PDFs; no downloads or AWS."""
import csv
from copy import deepcopy
import io
import json
import unittest

from research_batch import BATCH, MANIFEST, read_pdf, validate_row, project_v2
from schema import Catalog, ValidationError, digest


class FinancialResearchBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.specs = json.loads((BATCH / "selection.json").read_text())
        entries = {e["id"]: e for e in json.loads(MANIFEST.read_text())["entries"]}
        cls.data = []
        for spec in cls.specs:
            entry = entries[spec["source_id"]]
            raw = (BATCH / (spec["slug"] + "_candidates.csv")).read_bytes()
            rows = list(csv.DictReader(io.StringIO(raw.decode(), newline="")))
            cls.data.append((spec, entry, raw, rows, read_pdf(entry)))

    def test_twenty_exact_quotes_contexts_and_document_hashes(self):
        self.assertEqual([len(d[3]) for d in self.data], [6, 7, 7])
        for spec, entry, raw, rows, pages in self.data:
            for row in rows:
                validate_row(row, pages[int(row["pdf_page"])], entry["sha256"])
                self.assertEqual(row["ticker"], entry["ticker"])
                self.assertNotEqual(row["ticker"], "XIU.TO")
                self.assertEqual(row["fiscal_year"], "2025")
                self.assertTrue(row["disclosed_fact"] and row["interpretation"] and row["limitations"])

    def test_v2_catalogs_preserve_quotes_pages_and_unknown_direction(self):
        for spec, entry, raw, rows, pages in self.data:
            stored = Catalog.from_bytes((BATCH / (spec["slug"] + "_catalog.json")).read_bytes())
            self.assertEqual(len(stored.documents), 1)
            self.assertEqual(len(stored.passages), len(rows))
            self.assertEqual(stored.contexts, ())
            by_id = {r["evidence_id"]: r for r in rows}
            for passage in stored.passages:
                row = by_id[passage.research_id]
                self.assertEqual(passage.excerpt_original, row["excerpt"])
                self.assertEqual(passage.pdf_page, int(row["pdf_page"]))
                self.assertEqual(passage.printed_page, row["printed_page"])
                self.assertEqual(passage.stock_return_direction, "unknown")
                self.assertEqual(passage.quote_verification.status, "verified")
                self.assertEqual(passage.quote_verification.source_artifact_sha256, digest(raw))

    def test_cpkc_provenance_stays_pending_even_with_verified_quotes(self):
        spec, entry, raw, rows, pages = self.data[2]
        catalog = Catalog.from_bytes((BATCH / (spec["slug"] + "_catalog.json")).read_bytes())
        self.assertEqual(catalog.documents[0].source_verification.status, "unverified")
        self.assertFalse(catalog.documents[0].source_url_verified_claim)
        self.assertTrue(all(r["source_provenance_status"] == "pending_issuer_to_cdn" for r in rows))
        changed = dict(rows[0], url_verified="True")
        with self.assertRaises(ValidationError):
            validate_row(changed, pages[int(changed["pdf_page"])], entry["sha256"])

    def test_quote_edit_wrong_page_and_hash_are_rejected(self):
        _, entry, _, rows, pages = self.data[0]
        r = rows[0]
        for altered, page, sha in [(dict(r, excerpt=r["excerpt"] + " invented"), pages[79], entry["sha256"]),
                                   (r, pages[130], entry["sha256"]), (r, pages[79], "0" * 64)]:
            with self.subTest(sha=sha), self.assertRaises(ValidationError):
                validate_row(altered, page, sha)

    def test_context_removal_is_rejected(self):
        _, entry, _, rows, pages = self.data[0]
        with self.assertRaises(ValidationError):
            validate_row(dict(rows[0], source_context_after=""), pages[79], entry["sha256"])

    def test_financial_table_requires_units_scope_columns_and_notes(self):
        _, entry, _, rows, pages = self.data[0]
        for field in ("title", "units", "columns", "scope", "footnote_review"):
            table = json.loads(rows[0]["table_context"])
            table[field] = ""
            with self.subTest(field=field), self.assertRaises(ValidationError):
                validate_row(dict(rows[0], table_context=json.dumps(table)), pages[79], entry["sha256"])

    def test_currency_and_sensitivity_limitations_are_in_original_pages(self):
        cnq = self.data[1][4]
        cp = self.data[2][4]
        self.assertIn("All dollar amounts are referenced in millions of Canadian dollars", cnq[15])
        self.assertIn("Canadian dollars unless specifically noted otherwise", cp[17])
        quote = self.data[1][3][-1]["excerpt"]
        self.assertIn("fourth quarter of\n2025", quote)
        self.assertIn("all other variables being\nheld constant", quote)
        self.assertIn("not necessarily indicative of future results", quote)

    def test_printed_pages_and_context_disambiguate_rbc_tables(self):
        r = self.data[0][3]
        self.assertEqual([(x["pdf_page"], x["printed_page"]) for x in r],
                         [("79","77"),("130","128"),("131","129"),("132","130"),("133","131"),("185","183")])
        self.assertNotIn("Canada (3)", r[2]["source_context_before"])
        self.assertIn("Canada (2)", r[4]["source_context_before"])
        self.assertIn("Total PCL on impaired loans", r[3]["source_context_after"])

    def test_stock_direction_is_never_derived_from_operational_evidence(self):
        _, entry, _, rows, pages = self.data[1]
        with self.assertRaises(ValidationError):
            validate_row(dict(rows[0], direction="positive", stock_return_direction="positive"),
                         pages[21], entry["sha256"])

    def test_validation_receipt_matches_candidate_files(self):
        receipt = json.loads((BATCH / "validation_receipt.json").read_text())
        for record, data in zip(receipt["documents"], self.data):
            self.assertEqual(record["csv_sha256"], digest(data[2]))
            self.assertEqual(record["sha256"], data[1]["sha256"])


if __name__ == "__main__":
    unittest.main()
