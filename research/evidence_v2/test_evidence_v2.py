"""Offline contract and data-loss tests. No SDK, credentials, network or disk writes."""

import csv
from dataclasses import replace
import io
import json
from pathlib import Path
import unittest

from catalog import (CURRENT_KEY, CatalogConflict, EmptyBatch, PublicationPlan,
                     activate_plan, load_active, prepare_publication,
                     publish_research_batch, seed_demo_store)
from demo import DEFAULT_CSV, dummy_existing_catalog
from import_candidates import attach_holding_context, parse_candidates, read_candidates
from memory_s3 import MemoryS3, MissingObject, PreconditionFailed, SimulatedStorageError
from schema import (Catalog, EvidenceContext, ValidationError, Verification, canonical_bytes,
                    context_id, document_id, evidence_id)


PDF_SHA = "e5707264468a705945d2b7e078373ca12fedbbe51213e566f11c82a95f970e2b"


def csv_rows():
    return list(csv.DictReader(io.StringIO(DEFAULT_CSV.read_bytes().decode("utf-8-sig"), newline="")))


def altered_csv(change):
    rows = csv_rows()
    change(rows)
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8-sig")


class ImportAndSchemaTests(unittest.TestCase):
    def setUp(self):
        self.imported = read_candidates(DEFAULT_CSV)
        self.catalog = self.imported.catalog

    def test_real_supplied_candidates_preserve_all_quotes_pages_and_claims(self):
        self.assertEqual(len(self.catalog.documents), 1)
        self.assertEqual(len(self.catalog.passages), 5)
        doc = self.catalog.documents[0]
        self.assertEqual(doc.sha256, PDF_SHA)
        self.assertEqual(doc.document_id, document_id(PDF_SHA))
        self.assertEqual(doc.issuer, "Alimentation Couche-Tard inc.")
        self.assertEqual(doc.document_title, "Rapport annuel 2026")
        self.assertEqual(doc.fiscal_year_end, "2026-04-26")
        self.assertIsNone(doc.publication_date)  # Do not infer 2026-06-23 from the filename.
        self.assertEqual(doc.language, "fr")
        self.assertEqual([(p.pdf_page, p.printed_page) for p in self.catalog.passages],
                         [(66, "64"), (66, "64"), (66, "64"), (41, "39"), (67, "65")])
        for row, passage in zip(csv_rows(), self.catalog.passages):
            self.assertEqual(passage.excerpt_original, row["excerpt"])
            self.assertEqual(passage.research_id, row["evidence_id"])
            self.assertEqual(passage.section, row["section"])
            self.assertEqual(passage.interpretation, row["interpretation"])
            self.assertTrue(passage.quote_verified_claim)
            self.assertEqual(passage.quote_verification.status, "reported_verified")
            self.assertEqual(passage.stock_return_direction, "unknown")
        self.assertIn("73,0 %2", self.catalog.passages[1].excerpt_original)
        self.assertIn("marge brute1", self.catalog.passages[1].excerpt_original)

    def test_no_invented_official_source_or_verification(self):
        doc = self.catalog.documents[0]
        self.assertIsNone(doc.source_url)
        self.assertFalse(doc.source_url_verified_claim)
        self.assertEqual(doc.source_verification.status, "unverified")
        self.assertEqual(doc.issuer_verification.status, "unverified")
        self.assertEqual(doc.hash_verification.status, "reported_verified")
        self.assertEqual(doc.source_link_status, "not_supplied")
        self.assertIsNone(doc.s3_key)

    def test_boolean_false_is_not_truthy_and_true_requires_a_url(self):
        changed = altered_csv(lambda rows: rows[0].update(quote_verified="False"))
        passage = parse_candidates(changed).catalog.passages[0]
        self.assertFalse(passage.quote_verified_claim)
        self.assertEqual(passage.quote_verification.status, "unverified")
        with self.assertRaises(ValidationError):
            parse_candidates(altered_csv(lambda rows: rows[0].update(url_verified="True")))
        with self.assertRaises(ValidationError):
            parse_candidates(altered_csv(lambda rows: rows[0].update(quote_verified="yes")))

    def test_even_a_claimed_verified_url_is_not_independently_verified(self):
        def change(rows):
            for row in rows:
                row.update(source_url="https://example.invalid/research.pdf", url_verified="True")
        doc = parse_candidates(altered_csv(change)).catalog.documents[0]
        self.assertTrue(doc.source_url_verified_claim)
        self.assertEqual(doc.source_verification.status, "reported_verified")
        self.assertEqual(doc.source_link_status, "unknown")

    def test_ids_ignore_csv_order_and_category_but_not_original_quote_page_or_document(self):
        reordered = parse_candidates(altered_csv(lambda rows: rows.reverse())).catalog
        self.assertEqual({p.evidence_id for p in reordered.passages},
                         {p.evidence_id for p in self.catalog.passages})
        original = self.catalog.passages[0]
        changed = parse_candidates(altered_csv(lambda rows: rows[0].update(channel_candidate="new_description")))
        self.assertEqual(changed.catalog.passages[0].evidence_id, original.evidence_id)
        for args in ((original.document_id, 67, original.excerpt_original),
                     (original.document_id, 66, original.excerpt_original + " "),
                     (document_id("a" * 64), 66, original.excerpt_original)):
            self.assertNotEqual(evidence_id(*args), original.evidence_id)

    def test_malformed_hash_page_and_duplicate_ids_are_rejected(self):
        for mutation in (lambda rows: rows[0].update(sha256="bad"),
                         lambda rows: rows[0].update(pdf_page="0"),
                         lambda rows: rows[1].update(evidence_id=rows[0]["evidence_id"])):
            with self.subTest(mutation=mutation), self.assertRaises(ValidationError):
                parse_candidates(altered_csv(mutation))

    def test_operational_text_cannot_gain_stock_return_direction(self):
        for direction in ("positive", "negative", "mixed"):
            with self.subTest(direction=direction), self.assertRaises(ValidationError):
                replace(self.catalog.passages[0], stock_return_direction=direction).validate()

    def test_verified_status_needs_a_verification_record(self):
        with self.assertRaises(ValidationError):
            Verification(status="verified").validate()

    def test_roundtrip_preserves_metadata_exactly(self):
        restored = Catalog.from_bytes(self.catalog.to_bytes())
        self.assertEqual(restored.to_bytes(), self.catalog.to_bytes())
        self.assertEqual({p.evidence_id: p for p in restored.passages},
                         {p.evidence_id: p for p in self.catalog.passages})

    def test_legacy_or_unknown_schema_is_rejected_not_silently_migrated(self):
        for data in ({"evidence": []}, {**json.loads(self.catalog.to_bytes()), "schema_version": 1}):
            with self.assertRaises(ValidationError):
                Catalog.from_bytes(canonical_bytes(data))

    def test_holding_context_preserves_company_identity(self):
        result = attach_holding_context(self.catalog, "XIU.TO", "2026-11-12",
                                        "team-reported-holdings", {"ATD.TO": "ATD"})
        self.assertEqual(len(result.contexts), 5)
        self.assertTrue(all(p.subject_ticker == "ATD.TO" for p in result.passages))
        self.assertTrue(all(c.association_type == "holding" for c in result.contexts))
        self.assertTrue(all(c.investigation_ticker == "XIU.TO" for c in result.contexts))
        self.assertEqual(Catalog.from_bytes(result.to_bytes()).to_bytes(), result.to_bytes())

    def test_direct_etf_context_is_distinct_and_cannot_relabel_company_evidence(self):
        p = self.catalog.passages[0]
        args = (p.evidence_id, "XIU.TO", "direct_etf", "XIU.TO", None, None, None)
        context = EvidenceContext(context_id(*args), *args)
        with self.assertRaises(ValidationError):
            Catalog(self.catalog.documents, self.catalog.passages, (context,)).validate()
        etf = replace(p, subject_ticker="XIU.TO", subject_type="etf")
        Catalog(self.catalog.documents, (etf,), (context,)).validate()

    def test_orphan_context_or_passage_is_rejected(self):
        with self.assertRaises(ValidationError):
            Catalog((), self.catalog.passages).validate()
        with self.assertRaises(ValidationError):
            attach_holding_context(self.catalog, "XIU.TO", "2026-11-12", "source", {})


class PublicationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryS3()
        self.existing = dummy_existing_catalog()
        seed_demo_store(self.store, self.existing)
        self.batch = read_candidates(DEFAULT_CSV).catalog

    def test_partial_batch_preserves_existing_catalog_and_all_old_objects(self):
        before = self.store.snapshot()
        old = load_active(self.store)
        after = publish_research_batch(self.store, self.batch)
        self.assertEqual(len(after.catalog.documents), 2)
        self.assertEqual(len(after.catalog.passages), 6)
        self.assertIn(self.existing.passages[0], after.catalog.passages)
        self.assertEqual(self.store.get_object(Key=old.snapshot_key).body, self.existing.to_bytes())
        for key, value in before.items():
            if key != CURRENT_KEY:
                self.assertEqual(self.store.snapshot()[key], value)
        self.assertTrue(set(before).issubset(self.store.snapshot()))
        self.assertFalse(hasattr(self.store, "delete_object"))
        self.assertEqual(json.loads(self.store.get_object(Key=CURRENT_KEY).body)["previous_snapshot_key"],
                         old.snapshot_key)

    def test_empty_batch_performs_zero_writes(self):
        before = self.store.snapshot()
        with self.assertRaises(EmptyBatch):
            publish_research_batch(self.store, Catalog())
        self.assertEqual(self.store.snapshot(), before)

    def test_missing_catalog_blocks_without_bootstrapping(self):
        store = MemoryS3()
        with self.assertRaises(MissingObject):
            publish_research_batch(store, self.batch)
        self.assertEqual(store.snapshot(), {})

    def test_missing_snapshot_blocks_without_recovery(self):
        store = MemoryS3()
        store.put_object(Key=CURRENT_KEY, Body=self.store.get_object(Key=CURRENT_KEY).body,
                         if_none_match=True)
        before = store.snapshot()
        with self.assertRaises(MissingObject):
            publish_research_batch(store, self.batch)
        self.assertEqual(store.snapshot(), before)

    def test_read_failure_blocks_without_writes(self):
        before = self.store.snapshot()
        self.store.fail_next_read = True
        with self.assertRaises(SimulatedStorageError):
            publish_research_batch(self.store, self.batch)
        self.assertEqual(self.store.snapshot(), before)

    def test_document_metadata_conflict_blocks_without_writes(self):
        conflict = replace(self.existing.documents[0], issuer="Different issuer")
        incoming = Catalog((conflict,), self.existing.passages)
        before = self.store.snapshot()
        with self.assertRaises(CatalogConflict):
            publish_research_batch(self.store, incoming)
        self.assertEqual(self.store.snapshot(), before)

    def test_evidence_metadata_conflict_blocks_without_writes(self):
        incoming = Catalog(self.existing.documents,
                           (replace(self.existing.passages[0], section="Different section"),))
        before = self.store.snapshot()
        with self.assertRaises(CatalogConflict):
            publish_research_batch(self.store, incoming)
        self.assertEqual(self.store.snapshot(), before)

    def test_content_tampering_with_unchanged_id_is_rejected(self):
        incoming = Catalog(self.existing.documents,
                           (replace(self.existing.passages[0], excerpt_original="Altered quote"),))
        before = self.store.snapshot()
        with self.assertRaises(ValidationError):
            publish_research_batch(self.store, incoming)
        self.assertEqual(self.store.snapshot(), before)

    def test_reimport_is_idempotent_and_does_not_write(self):
        first = publish_research_batch(self.store, self.batch)
        before = self.store.snapshot()
        second = publish_research_batch(self.store, self.batch)
        self.assertEqual(second, first)
        self.assertEqual(self.store.snapshot(), before)

    def test_staging_failure_keeps_active_version(self):
        plan = prepare_publication(self.store, self.batch)
        from schema import digest
        from catalog import SNAPSHOT_PREFIX
        self.store.fail_put_key = SNAPSHOT_PREFIX + digest(plan.merged.to_bytes()) + ".json"
        before = self.store.snapshot()
        with self.assertRaises(SimulatedStorageError):
            activate_plan(self.store, plan)
        self.assertEqual(self.store.snapshot(), before)

    def test_failed_activation_preserves_old_version_and_retry_is_safe(self):
        plan = prepare_publication(self.store, self.batch)
        before = load_active(self.store)
        self.store.fail_put_key = CURRENT_KEY
        with self.assertRaises(SimulatedStorageError):
            activate_plan(self.store, plan)
        self.assertEqual(load_active(self.store), before)
        self.assertGreater(len(self.store.snapshot()), 2)  # Staged, but invisible to readers.
        self.store.fail_put_key = None
        after = activate_plan(self.store, plan)
        self.assertEqual(len(after.catalog.passages), 6)

    def test_stale_partial_batch_cannot_erase_another_batch(self):
        stale = prepare_publication(self.store, self.batch)
        other = dummy_existing_catalog("RY.TO", "second-batch")
        publish_research_batch(self.store, other)
        before = self.store.snapshot()
        with self.assertRaises(CatalogConflict):
            activate_plan(self.store, stale)
        self.assertEqual(self.store.snapshot(), before)
        result = publish_research_batch(self.store, self.batch)
        self.assertIn(other.passages[0], result.catalog.passages)
        self.assertIn(self.existing.passages[0], result.catalog.passages)

    def test_pointer_compare_and_swap_rejects_stale_token(self):
        old = self.store.get_object(Key=CURRENT_KEY)
        self.store.put_object(Key=CURRENT_KEY, Body=old.body, if_match=old.etag)
        with self.assertRaises(PreconditionFailed):
            self.store.put_object(Key=CURRENT_KEY, Body=b"bad", if_match=old.etag)

    def test_tampered_snapshot_fails_digest_validation(self):
        active = load_active(self.store)
        obj = self.store.get_object(Key=active.snapshot_key)
        self.store.put_object(Key=active.snapshot_key, Body=b"{}", if_match=obj.etag)
        before = self.store.snapshot()
        with self.assertRaises(ValidationError):
            publish_research_batch(self.store, self.batch)
        self.assertEqual(self.store.snapshot(), before)

    def test_handcrafted_plan_cannot_remove_existing_records(self):
        bad_plan = PublicationPlan(load_active(self.store), self.batch)
        before = self.store.snapshot()
        with self.assertRaises(CatalogConflict):
            activate_plan(self.store, bad_plan)
        self.assertEqual(self.store.snapshot(), before)

    def test_bootstrap_cannot_overwrite_existing_store(self):
        before = self.store.snapshot()
        with self.assertRaises(CatalogConflict):
            seed_demo_store(self.store, self.existing)
        self.assertEqual(self.store.snapshot(), before)

    def test_real_or_unknown_client_is_rejected_before_any_call(self):
        class UnknownClient:
            def get_object(self, **kwargs):
                self.fail = True
                raise AssertionError("Must never be called")
        client = UnknownClient()
        with self.assertRaises(TypeError):
            publish_research_batch(client, self.batch)
        self.assertFalse(hasattr(client, "fail"))


if __name__ == "__main__":
    unittest.main()
