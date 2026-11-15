"""Tests for the five-constituent XIU resolver. Standard library only; no network or AWS.

Synthetic holdings exercise the guards. Tests marked "real inputs" read the authorized local files
(~/Downloads/xiu_holdings.csv and the research register) and skip if they are absent.
"""
import csv
from dataclasses import replace
import io
import json
from pathlib import Path
import unittest
from unittest import mock

import xiu_resolver_5 as r5
from import_candidates import parse_candidates
from schema import ValidationError, digest
from xiu_holdings import XIU_DATE, parse_holdings

def _real_inputs_available():
    try:
        r5.load_inputs()
        return True
    except ValidationError:
        return False


REAL = _real_inputs_available()
NAMES = {t: n for t, (_, n) in r5.MAPPINGS.items()}


def holdings_csv(rows=None, date="Nov 12, 2026"):
    """rows: list of (ticker, name, weight, asset_class, exchange, currency)."""
    rows = rows if rows is not None else [
        ("RY", NAMES["RY.TO"], "9.58"), ("CNQ", NAMES["CNQ.TO"], "3.45"), ("CP", NAMES["CP.TO"], "2.83"),
        ("CNR", NAMES["CNR.TO"], "2.39"), ("ATD", NAMES["ATD.TO"], "1.46"), ("OTHER", "SYNTHETIC REST", "80.29")]
    out = io.StringIO(newline="")
    w = csv.writer(out)
    w.writerow(["Fund Holdings as of", date])
    w.writerow([" "])
    w.writerow(["Ticker", "Name", "Sector", "Asset Class", "Weight (%)", "Exchange", "Currency"])
    for row in rows:
        ticker, name, weight = row[:3]
        asset_class, exchange, currency = row[3:6] if len(row) > 3 else ("Equity", "Toronto Stock Exchange", "CAD")
        w.writerow([ticker, name, "Synthetic", asset_class, weight, exchange, currency])
    return out.getvalue().encode("utf-8-sig")


def snapshot(rows=None):
    """A synthetic snapshot dated 2026-11-12, parsed by the original parse_holdings."""
    raw = holdings_csv(rows)
    return parse_holdings(raw, digest(raw))


class MappingAndWeightGuards(unittest.TestCase):
    def test_all_five_reviewed_mappings_resolve(self):
        s = snapshot()
        for ticker, (holding, _) in r5.MAPPINGS.items():
            self.assertEqual(r5.validate_mapping(s, ticker).ticker_original, holding)

    def test_explicit_three_new_mappings(self):
        self.assertEqual({t: r5.MAPPINGS[t][0] for t in ("RY.TO", "CNQ.TO", "CP.TO")},
                         {"RY.TO": "RY", "CNQ.TO": "CNQ", "CP.TO": "CP"})

    def test_missing_holding_is_rejected(self):
        s = snapshot([("RY", NAMES["RY.TO"], "9.58"), ("OTHER", "X", "90.42")])
        with self.assertRaisesRegex(ValidationError, "CP is missing"):
            r5.validate_mapping(s, "CP.TO")

    def test_ambiguous_holding_is_rejected(self):
        s = snapshot([("CP", NAMES["CP.TO"], "1.40"), ("CP", NAMES["CP.TO"], "1.43"), ("OTHER", "X", "97.17")])
        with self.assertRaisesRegex(ValidationError, "ambiguous"):
            r5.validate_mapping(s, "CP.TO")

    def test_same_company_under_two_tickers_is_ambiguous(self):
        s = snapshot([("RY", NAMES["RY.TO"], "9.0"), ("RY.PR", NAMES["RY.TO"], "0.58"), ("OTHER", "X", "90.42")])
        with self.assertRaisesRegex(ValidationError, "several rows"):
            r5.validate_mapping(s, "RY.TO")

    def test_wrong_company_behind_the_ticker_is_rejected(self):
        s = snapshot([("CP", "CANADIAN PACIFIC SOMETHING ELSE", "2.83"), ("OTHER", "X", "97.19")])
        with self.assertRaisesRegex(ValidationError, "reviewed"):
            r5.validate_mapping(s, "CP.TO")

    def test_non_tsx_or_non_equity_row_is_rejected(self):
        s = snapshot([("CNQ", NAMES["CNQ.TO"], "3.45", "Equity", "New York Stock Exchange Inc.", "USD"),
                      ("OTHER", "X", "96.55")])
        with self.assertRaisesRegex(ValidationError, "CAD TSX equity"):
            r5.validate_mapping(s, "CNQ.TO")

    def test_unreviewed_ticker_is_rejected(self):
        with self.assertRaisesRegex(ValidationError, "No reviewed holding mapping"):
            r5.validate_mapping(snapshot(), "TD.TO")

    def test_inconsistent_weights_are_rejected(self):
        s = snapshot([("RY", NAMES["RY.TO"], "9.58"), ("OTHER", "X", "60.00")])  # displayed total 69.58%
        rows = {"RY.TO": r5.validate_mapping(s, "RY.TO")}
        with self.assertRaisesRegex(ValidationError, "Inconsistent holdings weights"):
            r5.check_weights(s, rows)

    def test_rounded_total_is_accepted_and_not_renormalized(self):
        s = snapshot()  # sums to exactly 100.00 here; the real file shows 100.02
        total, documented = r5.check_weights(s, {t: r5.validate_mapping(s, t) for t in r5.MAPPINGS})
        self.assertEqual(str(documented), "19.71")

    def test_stale_holdings_date_is_rejected(self):
        with self.assertRaises(ValidationError):  # the original parser refuses a non-2026-11-12 date
            raw = holdings_csv(date="Nov 11, 2026")
            parse_holdings(raw, digest(raw))
        stale = replace(snapshot(), as_of="2026-11-11")
        with self.assertRaisesRegex(ValidationError, "Stale or wrong holdings snapshot"):
            r5.resolve_five(stale, None, {}, {}, {})


class DuplicateGuards(unittest.TestCase):
    def setUp(self):
        self.batch = parse_candidates((r5.ROOT / "candidates_cnq_2025.csv").read_bytes())

    def test_duplicate_research_id_across_sources_is_rejected(self):
        p = self.batch.catalog.passages[0]
        clash = replace(self.batch.catalog.passages[1], research_id=p.research_id)
        with self.assertRaisesRegex(ValidationError, "Duplicate research ID"):
            r5.check_unique({"a": [p], "b": [clash]})

    def test_duplicate_evidence_id_is_rejected_even_if_merge_would_collapse_it(self):
        p = self.batch.catalog.passages[0]
        with self.assertRaisesRegex(ValidationError, "Duplicate"):
            r5.check_unique({"register": [p], "batch": [p]})

    def test_distinct_ids_pass(self):
        r5.check_unique({"a": self.batch.catalog.passages})


@unittest.skipUnless(REAL, "real inputs not configured (copy local_inputs.example.json to local_inputs.json)")
class RealInputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = r5.resolve_local_inputs()
        cls.original = json.loads((r5.ROOT / "xiu_resolution.json").read_text())

    def test_reported_counts(self):
        s = self.result["scope"]
        self.assertEqual((s["document_count"], s["passage_count"], s["distinct_holdings_count"]), (5, 35, 5))
        self.assertEqual(s["passages_by_ticker"], {"ATD.TO": 5, "CNR.TO": 7, "RY.TO": 7, "CNQ.TO": 8, "CP.TO": 8})
        self.assertEqual(s["documented_holding_weight_pct"], "19.71")
        self.assertIn("NOT statistical beta coverage", s["weight_meaning"])
        self.assertEqual(self.result["holdings_snapshot"]["as_of"], XIU_DATE)
        self.assertFalse(self.result["holdings_snapshot"]["weights_renormalized"])

    def test_original_twelve_passages_are_preserved_exactly(self):
        new = {p["research_id"]: p for p in self.result["passages"]}
        self.assertEqual(len(self.original["passages"]), 12)
        for old in self.original["passages"]:
            mine = dict(new[old["research_id"]])
            self.assertEqual(mine.pop("evidence_batch"), "research_register_2026-11-15")
            self.assertEqual(mine, old, old["research_id"])  # every field, including quote and verification

    def test_original_documents_and_holdings_are_preserved(self):
        new_docs = {d["document_id"]: d for d in self.result["documents"]}
        for old in self.original["documents"]:
            mine = {k: v for k, v in new_docs[old["document_id"]].items()
                    if k not in ("evidence_batch", "metadata_review")}
            old = dict(old)
            mine["local_file_verification"].pop("checked_at"), old["local_file_verification"].pop("checked_at")
            self.assertEqual(mine, old)
        new_h = {h["ticker"]: h for h in self.result["holdings"]}
        for old in self.original["holdings"]:
            mine = dict(new_h[old["ticker"]])
            mine.pop("mapping_review")
            self.assertEqual(mine, old)

    def test_new_quotations_are_preserved_exactly(self):
        by_id = {p["research_id"]: p for p in self.result["passages"]}
        for name in ("candidates_rbc_2025.csv", "candidates_cnq_2025.csv", "candidates_cpkc_2025.csv"):
            for p in parse_candidates((r5.ROOT / name).read_bytes()).catalog.passages:
                row = by_id[p.research_id]
                self.assertEqual(row["excerpt_original"], p.excerpt_original)
                self.assertEqual((row["evidence_id"], row["pdf_page"], row["printed_page"], row["section"]),
                                 (p.evidence_id, p.pdf_page, p.printed_page, p.section))
                self.assertEqual(row["ticker"], p.subject_ticker)

    def test_each_passage_keeps_its_company_document_and_weight(self):
        docs = {d["document_id"]: d for d in self.result["documents"]}
        weights = {h["ticker"]: h["weight_pct_original"] for h in self.result["holdings"]}
        self.assertEqual(weights, {"ATD.TO": "1.46", "CNR.TO": "2.39", "RY.TO": "9.58", "CNQ.TO": "3.45", "CP.TO": "2.83"})
        for p in self.result["passages"]:
            self.assertEqual(p["holding_weight_pct_original"], weights[p["ticker"]])
            self.assertEqual(docs[p["document_id"]]["sha256"], p["document_sha256"])
            self.assertEqual(p["context"]["subject_ticker"], p["ticker"])
            self.assertEqual(p["context"]["investigation_ticker"], "XIU.TO")
            self.assertEqual((p["evidence_kind"], p["stock_return_direction"]), ("operational", "unknown"))

    def test_verification_is_not_promoted(self):
        for p in self.result["passages"]:
            if p["evidence_batch"] == "oil_batch_2025":
                self.assertEqual(p["verification"]["quote"]["status"], "reported_verified")
                self.assertEqual(p["verification"]["quote"]["method"], "candidate_csv_assertion")
                self.assertEqual(p["verification"]["official_provenance"]["status"], "unverified")
                self.assertIn("not re-run", p["verification"]["quote_pdf_text_check"]["scope"])
            else:
                self.assertEqual(p["verification"]["page_reference"], "reported_in_research_register_not_reextracted")

    def test_cpkc_provenance_stays_pending(self):
        cpkc = [d for d in self.result["documents"] if d["issuer"] == "Canadian Pacific Kansas City Limited"]
        self.assertEqual(len(cpkc), 1)
        self.assertEqual(cpkc[0]["provenance_status"], "pending_issuer_to_cdn_link")
        self.assertEqual(cpkc[0]["metadata_review"]["status"], "provenance_manual_review")
        self.assertFalse(cpkc[0]["source_url_verified_claim"])
        for p in self.result["passages"]:
            if p["ticker"] == "CP.TO":
                self.assertEqual(p["verification"]["provenance_status"], "pending_issuer_to_cdn_link")

    def test_statistics_are_separate_and_cp_has_no_beta(self):
        stats = self.result["statistical_relationships"]["by_ticker"]
        self.assertTrue(all(v["beta"] is None for v in stats.values()))
        self.assertEqual(stats["CP.TO"]["status"], "no_validated_beta_ticker_not_in_model_universe")
        for p in self.result["passages"]:
            self.assertFalse({"beta", "beta_simple", "contribution"} & set(p))
        contract = (r5.ROOT.parent.parent / "docs" / "data_contract.md").read_text()
        self.assertNotIn("CP.TO", contract)  # universe status matches the data contract
        for t in ("RY.TO", "CNQ.TO", "ATD.TO", "CNR.TO"):
            self.assertIn(t, contract)

    def test_missing_document_is_rejected(self):
        batch = r5.load_batch("CP.TO")
        broken = dict(batch[2], local_file="runs/20261115T131702Z_d4fbb4fa/DOES_NOT_EXIST.pdf")
        with mock.patch.object(r5, "load_batch", lambda t: (batch[0], batch[1], broken, batch[3]) if t == "CP.TO"
                               else _real_load(t)):
            with self.assertRaisesRegex(ValidationError, "source PDF missing"):
                r5.resolve_local_inputs()

    def test_document_missing_from_catalog_is_rejected(self):
        b = r5.load_batch("RY.TO")
        orphan = b[0].catalog.__class__((), b[0].catalog.passages)
        with self.assertRaises(ValidationError):  # schema: passage references a missing document
            orphan.validate()

    def test_output_file_matches_a_fresh_resolution(self):
        path = r5.ROOT / "xiu_resolution_5_companies.json"
        if not path.exists():
            self.skipTest("output not generated yet")
        saved = json.loads(path.read_text())
        for key in ("scope", "holdings", "statistical_relationships", "holdings_snapshot"):
            self.assertEqual(saved[key], self.result[key], key)
        strip = lambda p: {k: v for k, v in p.items() if k != "verification"}  # noqa: E731 (timestamps)
        self.assertEqual([strip(p) for p in saved["passages"]], [strip(p) for p in self.result["passages"]])


_real_load = r5.load_batch

if __name__ == "__main__":
    unittest.main()
