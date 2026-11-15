"""Portable tests: run on any machine with no real holdings, register or PDFs. Standard library only.

Everything here is SYNTHETIC (fixture holdings, fake PDF bytes, made-up quotes). It proves the input
configuration, its error messages, and the whole five-company resolution path work without ~/Downloads.
"""
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import inputs
import xiu_resolver_5 as r5
from import_candidates import FIELDS, parse_candidates
from schema import (Catalog, Document, EvidencePassage, Verification, ValidationError, digest, document_id,
                    evidence_id)
from xiu_holdings import parse_holdings

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "synthetic_xiu_holdings.csv"


def write_config(folder, holdings, register, **overrides):
    cfg = {"xiu_holdings": {"path": str(holdings), "sha256": digest(Path(holdings).read_bytes()) if Path(holdings).exists() else "0" * 64,
                            "as_of": "2026-11-12", "source": {"issuer": "SYNTHETIC"}},
           "research_register": {"path": str(register), "sha256": digest(Path(register).read_bytes()) if Path(register).exists() else "0" * 64}}
    for key, value in overrides.items():
        cfg[key].update(value)
    path = Path(folder) / "cfg.json"
    path.write_text(json.dumps(cfg))
    return path


class InputConfigTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.holdings = self.tmp / "h.csv"
        self.holdings.write_bytes(FIXTURE.read_bytes())
        self.register = self.tmp / "r.xlsx"
        self.register.write_bytes(b"SYNTHETIC REGISTER BYTES")

    def test_fixture_is_synthetic_and_parses_with_the_original_parser(self):
        raw = FIXTURE.read_bytes()
        self.assertIn(b"SYNTHETIC", raw)
        snap = parse_holdings(raw, digest(raw))
        self.assertEqual(snap.as_of, "2026-11-12")
        self.assertEqual({r.ticker_original for r in snap.rows} >= {"RY", "CNQ", "CP", "CNR", "ATD"}, True)

    def test_valid_config_resolves_relative_paths(self):
        cfg = write_config(self.tmp, "h.csv", "r.xlsx")
        cfg_data = json.loads(cfg.read_text())
        cfg_data["xiu_holdings"]["sha256"] = digest(self.holdings.read_bytes())
        cfg_data["research_register"]["sha256"] = digest(self.register.read_bytes())
        cfg.write_text(json.dumps(cfg_data))
        loaded = inputs.load_inputs(cfg)
        self.assertEqual(loaded.holdings.path, self.holdings.resolve())
        self.assertEqual(loaded.holdings.meta["as_of"], "2026-11-12")

    def test_missing_config_explains_how_to_create_it(self):
        with self.assertRaisesRegex(inputs.MissingInput, "local_inputs.example.json"):
            inputs.load_inputs(self.tmp / "nope.json")

    def test_missing_file_names_key_path_and_hash(self):
        cfg = write_config(self.tmp, self.tmp / "absent.csv", self.register)
        with self.assertRaisesRegex(inputs.MissingInput, r"Missing input 'xiu_holdings': .*absent\.csv \(expected SHA-256 0{64}\)"):
            inputs.load_inputs(cfg)

    def test_wrong_hash_is_refused(self):
        cfg = write_config(self.tmp, self.holdings, self.register, xiu_holdings={"sha256": "f" * 64})
        with self.assertRaisesRegex(ValidationError, "expected f{64}"):
            inputs.load_inputs(cfg)

    def test_incomplete_entry_is_refused(self):
        cfg = write_config(self.tmp, self.holdings, self.register, xiu_holdings={"as_of": ""})
        with self.assertRaisesRegex(ValidationError, "needs the fields"):
            inputs.load_inputs(cfg)

    def test_environment_variable_is_honoured(self):
        cfg = write_config(self.tmp, self.holdings, self.register)
        with mock.patch.dict(os.environ, {inputs.ENV: str(cfg)}):
            self.assertEqual(inputs.load_inputs().config_path, cfg.resolve())

    def test_resolver_refuses_a_config_for_another_snapshot(self):
        cfg = write_config(self.tmp, self.holdings, self.register)  # valid file, but not the reviewed hash
        with self.assertRaisesRegex(ValidationError, "other than the reviewed snapshot"):
            r5.resolve_local_inputs(cfg)

    def test_stale_date_in_fixture_is_rejected(self):
        raw = FIXTURE.read_bytes().replace(b"Nov 12, 2026", b"Nov 05, 2026")
        with self.assertRaisesRegex(ValidationError, "Incorrect official holdings date"):
            parse_holdings(raw, digest(raw))


def synthetic_world(tmp):
    """Synthetic register (ATD, CNR) and batches (RY, CNQ, CP) with fake PDFs under a fake acquisitions root."""
    acq = Path(tmp) / "acq"
    (acq / "runs").mkdir(parents=True)
    docs, passages, paths, observations, batches = [], [], {}, {}, {}
    def pdf(name):
        raw = b"%PDF-SYNTHETIC " + name.encode()
        p = acq / "runs" / f"{name}.pdf"
        p.write_bytes(raw)
        return p, digest(raw)
    for ticker in ("ATD.TO", "CNR.TO"):
        p, sha = pdf(ticker)
        d = Document(document_id(sha), sha, "SYNTHETIC issuer", "SYNTHETIC report", p.name, "en", 2025, "2025-12-31",
                     None, None, False, "not_supplied", Verification(), Verification(), Verification())
        q = f"SYNTHETIC quote for {ticker}."
        passages.append(EvidencePassage(evidence_id(d.document_id, 1, q), d.document_id, f"SYN-{ticker}", ticker,
                                        "company", 1, "1", "Synthetic", q, "operational", "test", "unknown", "",
                                        False, Verification()))
        docs.append(d)
        paths[d.document_id] = p
        observations[d.document_id] = {"synthetic": True}
    register = Catalog(tuple(docs), tuple(passages))
    for ticker in ("RY.TO", "CNQ.TO", "CP.TO"):
        p, sha = pdf(ticker)
        out = io.StringIO(newline="")
        w = csv.DictWriter(out, fieldnames=FIELDS)
        w.writeheader()
        quote = f"SYNTHETIC quote for {ticker}."
        w.writerow({"evidence_id": f"SYN-{ticker}", "ticker": ticker, "issuer": "SYNTHETIC issuer",
                    "document_title": "SYNTHETIC report", "fiscal_year": "2025", "fiscal_year_end": "2025-12-31",
                    "language": "en", "pdf_page": "1", "printed_page": "1", "section": "Synthetic",
                    "channel_candidate": "test", "direction": "unknown", "excerpt": quote,
                    "interpretation": "OUR INTERPRETATION (not issuer text): synthetic", "document_file": p.name,
                    "sha256": sha, "source_url": "", "url_verified": "False", "quote_verified": "False"})
        raw = out.getvalue().encode()
        batch = parse_candidates(raw)
        ev = batch.catalog.passages[0].evidence_id
        status = "pending_issuer_to_cdn_link" if ticker == "CP.TO" else "official_issuer_url_retrieved"
        sidecar = {"document": {"sha256": sha, "provenance_status": status, "provenance_note": "synthetic"},
                   "candidates": [{"evidence_id": ev, "quote_verification": Verification().__dict__,
                                   "verification": {"match_method": "synthetic"}}]}
        receipt = {"id": ticker, "sha256": sha, "local_file": f"runs/{p.name}", "retrieved_at": "synthetic",
                   "official_url": "https://example.invalid/x.pdf", "landing_url": "https://example.invalid/",
                   "http_receipt": {"final_url": "https://example.invalid/x.pdf"},
                   "content_validation": {"page_count": 1}}
        batches[ticker] = (batch, sidecar, receipt, digest(raw))
    return acq, register, paths, observations, batches


class PortableResolution(unittest.TestCase):
    def test_five_company_resolution_runs_on_synthetic_inputs_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            acq, register, paths, observations, batches = synthetic_world(tmp)
            raw = FIXTURE.read_bytes()
            snapshot = parse_holdings(raw, digest(raw))
            with mock.patch.object(r5, "ACQUISITIONS", acq):
                out = r5.resolve_five(snapshot, register, paths, observations, batches,
                                      checked_at="2026-11-15T00:00:00+00:00")
        s = out["scope"]
        self.assertEqual((s["document_count"], s["passage_count"], s["distinct_holdings_count"]), (5, 5, 5))
        self.assertEqual(s["documented_holding_weight_pct"], "19.71")
        cp = next(d for d in out["documents"] if d.get("provenance_status") == "pending_issuer_to_cdn_link")
        self.assertIn("CP.TO", cp["document_file"])
        self.assertIsNone(out["statistical_relationships"]["by_ticker"]["CP.TO"]["beta"])

    def test_missing_pdf_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            acq, register, paths, observations, batches = synthetic_world(tmp)
            (acq / "runs" / "CNQ.TO.pdf").unlink()
            raw = FIXTURE.read_bytes()
            with mock.patch.object(r5, "ACQUISITIONS", acq):
                with self.assertRaisesRegex(ValidationError, "CNQ.TO: source PDF missing"):
                    r5.resolve_five(parse_holdings(raw, digest(raw)), register, paths, observations, batches)


if __name__ == "__main__":
    unittest.main()
