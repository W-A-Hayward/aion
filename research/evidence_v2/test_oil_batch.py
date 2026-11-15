"""Validation of the RBC / CNQ / CPKC oil-exposure batch. Standard library only.

    python3 -B -m unittest discover -s research/evidence_v2 -p 'test_*.py' -v
    OIL_BATCH_PDF=1 python3 -B -m unittest research/evidence_v2/test_oil_batch.py   # + re-verify on the PDFs (slow, macOS)
"""
import json
import os
import re
import shutil
import sys
import unittest
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from import_candidates import FIELDS, parse_candidates  # noqa: E402
from oil_batch_2025 import CANDIDATES, RUN_DIR, SOURCES  # noqa: E402
from schema import Catalog, ValidationError  # noqa: E402

SLUGS = {"RBC_2025_EN": "rbc", "CNQ_2025_EN": "cnq", "CPKC_2025_EN": "cpkc"}
TICKERS = {"RBC_2025_EN": "RY.TO", "CNQ_2025_EN": "CNQ.TO", "CPKC_2025_EN": "CP.TO"}
# Wording that would assert a share-price direction rather than an operating fact.
STOCK_DIRECTION = re.compile(r"\b(stock|share price|shares|share returns?)\b[^.]{0,40}\b(will|would|should|tends? to)\b"
                             r"[^.]{0,20}\b(rise|fall|increase|decrease|outperform|underperform|go up|go down)", re.I)


def load(source_id):
    slug = SLUGS[source_id]
    raw = (HERE / f"candidates_{slug}_2025.csv").read_bytes()
    sidecar = json.loads((HERE / f"candidates_{slug}_2025.verification.json").read_text())
    return raw, parse_candidates(raw), sidecar


class OilBatchFiles(unittest.TestCase):
    def test_csvs_pass_the_existing_importer_and_schema(self):
        for source_id in SOURCES:
            raw, batch, _ = load(source_id)
            batch.catalog.validate()
            Catalog.from_bytes(batch.catalog.to_bytes())  # lossless round trip
            self.assertEqual(raw.split(b"\r\n", 1)[0].decode().split(","), list(FIELDS))

    def test_five_to_eight_candidates_per_company_linked_to_its_own_ticker(self):
        for source_id, ticker in TICKERS.items():
            _, batch, sidecar = load(source_id)
            passages = batch.catalog.passages
            self.assertTrue(5 <= len(passages) <= 8, (source_id, len(passages)))
            self.assertEqual({p.subject_ticker for p in passages}, {ticker})
            self.assertEqual({p.subject_type for p in passages}, {"company"})
            self.assertEqual(len(batch.catalog.documents), 1)
            self.assertEqual(sidecar["document"]["ticker"], ticker)

    def test_operational_evidence_never_carries_a_stock_direction(self):
        for source_id in SOURCES:
            _, batch, sidecar = load(source_id)
            for p in batch.catalog.passages:
                self.assertEqual((p.evidence_kind, p.stock_return_direction), ("operational", "unknown"))
                self.assertTrue(p.interpretation.startswith("OUR INTERPRETATION (not issuer text): "))
                self.assertIsNone(STOCK_DIRECTION.search(p.interpretation), p.research_id)
            for c in sidecar["candidates"]:
                self.assertEqual(c["stock_return_direction"], "unknown")
                self.assertNotEqual(c["company_disclosed_text"], c["our_interpretation"])

    def test_direction_guard_catches_a_claim(self):
        self.assertIsNotNone(STOCK_DIRECTION.search("so the share price will rise with oil"))
        self.assertIsNone(STOCK_DIRECTION.search("operating cash flow changes by $409 million"))

    def test_sidecar_matches_catalog_and_definitions(self):
        defs = {c["id"]: c for c in CANDIDATES}
        for source_id in SOURCES:
            _, batch, sidecar = load(source_id)
            by_research = {p.research_id: p for p in batch.catalog.passages}
            self.assertEqual(set(by_research), {c["research_id"] for c in sidecar["candidates"]})
            for c in sidecar["candidates"]:
                p, d = by_research[c["research_id"]], defs[c["research_id"]]
                self.assertEqual(c["evidence_id"], p.evidence_id)
                self.assertEqual(c["company_disclosed_text"], p.excerpt_original)
                self.assertEqual(p.excerpt_original, d["excerpt"])
                self.assertEqual((p.pdf_page, p.printed_page, p.section), (d["pdf_page"], d["printed_page"], d["section"]))
                self.assertTrue(c["context_before"] or c["context_after"])

    def test_every_quote_passed_page_verification(self):
        for source_id in SOURCES:
            _, batch, sidecar = load(source_id)
            for c in sidecar["candidates"]:
                v = c["verification"]
                self.assertTrue(v["passed"], c["research_id"])
                self.assertEqual(v["occurrences_on_page"], 1)
                self.assertTrue(all(v["anchors_found"].values()))
                self.assertTrue(v["printed_page_check"]["offset_match"] and not v["printed_page_check"]["two_page_spread"])
                self.assertEqual(c["quote_verification"]["status"], "verified")
            for p in batch.catalog.passages:
                self.assertTrue(p.quote_verified_claim)

    def test_tables_keep_headings_units_and_footnotes(self):
        for source_id in SOURCES:
            _, _, sidecar = load(source_id)
            for c in sidecar["candidates"]:
                if c["form"] == "table_row":
                    self.assertTrue(c["table"]["title"] and c["table"]["units"] and c["table"]["columns"], c["research_id"])
                    self.assertGreaterEqual(len(c["anchors"]), 2, c["research_id"])

    def test_provenance_cpkc_pending_others_official(self):
        for source_id in SOURCES:
            raw, batch, sidecar = load(source_id)
            doc = batch.catalog.documents[0]
            self.assertFalse(doc.source_url_verified_claim)  # nothing was re-fetched in this batch
            self.assertEqual(doc.source_verification.status, "unverified")
            self.assertFalse(sidecar["document"]["url_verified_in_this_batch"])
        cpkc = load("CPKC_2025_EN")[2]["document"]
        self.assertEqual(cpkc["provenance_status"], "pending_issuer_to_cdn_link")
        self.assertIn("PROVENANCE PENDING", cpkc["provenance_note"])
        self.assertIn("q4cdn.com", cpkc["official_url"])
        for source_id in ("RBC_2025_EN", "CNQ_2025_EN"):
            self.assertEqual(load(source_id)[2]["document"]["provenance_status"], "official_issuer_url_retrieved")

    def test_document_hash_matches_receipt_and_file(self):
        for source_id in SOURCES:
            _, batch, sidecar = load(source_id)
            receipt = json.loads((HERE / RUN_DIR / f"{source_id}.receipt.json").read_text())
            self.assertEqual(batch.catalog.documents[0].sha256, receipt["sha256"])
            pdf = HERE.parent / "source_documents" / receipt["local_file"]
            if pdf.exists():
                self.assertEqual(sha256(pdf.read_bytes()).hexdigest(), receipt["sha256"])

    def test_tampered_quote_is_rejected_by_the_schema(self):
        raw, _, _ = load("CNQ_2025_EN")
        tampered = raw.replace(b"$ 409 $ 0.20 $ 409", b"$ 490 $ 0.20 $ 409")
        batch = parse_candidates(tampered)  # still parses: the CSV alone cannot know the PDF...
        sidecar_ids = {c["evidence_id"] for c in load("CNQ_2025_EN")[2]["candidates"]}
        self.assertNotEqual({p.evidence_id for p in batch.catalog.passages}, sidecar_ids)  # ...but the IDs change
        # Marking operational evidence with a stock direction is refused by the existing schema.
        with self.assertRaisesRegex(ValidationError, "stock-return direction"):
            parse_candidates(raw.replace(b",unknown,", b",positive,", 1))


@unittest.skipUnless(os.environ.get("OIL_BATCH_PDF") == "1" and shutil.which("osascript"),
                     "set OIL_BATCH_PDF=1 on macOS to re-verify every quote against the PDFs")
class OilBatchAgainstPdfs(unittest.TestCase):
    def test_every_quote_reverifies_on_the_original_pdf_page(self):
        import build_oil_batch
        reports, failures = build_oil_batch.build(check_only=True)
        self.assertEqual(failures, [])
        self.assertEqual(sum(len(r["candidates"]) for r in reports.values()), len(CANDIDATES))


if __name__ == "__main__":
    unittest.main()
