"""Offline demonstration. Reading the CSV is its only filesystem operation."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from catalog import load_active, publish_research_batch, seed_demo_store
from import_candidates import attach_holding_context, read_candidates
from memory_s3 import MemoryS3
from schema import Catalog, Document, EvidencePassage, Verification, digest, document_id, evidence_id


DEFAULT_CSV = Path(__file__).parent / "fixtures" / "atd_candidates.csv"


def dummy_existing_catalog(ticker="ENB.TO", tag="baseline"):
    """A synthetic pre-existing record, NEVER a real Enbridge document or quote."""
    quote = f"SYNTHETIC TEST FIXTURE ({tag}). Not a financial disclosure."
    sha = digest(quote.encode("utf-8"))
    doc = Document(
        document_id=document_id(sha), sha256=sha, issuer="Fictional test issuer",
        document_title="SYNTHETIC EXISTING DOCUMENT", document_file=f"synthetic-{tag}.txt",
        language="en", fiscal_year=2026, fiscal_year_end="2026-01-01", publication_date=None,
        source_url=None, source_url_verified_claim=False, source_link_status="not_supplied",
        issuer_verification=Verification(), source_verification=Verification(),
        hash_verification=Verification(), doc_type="synthetic_fixture",
    )
    passage = EvidencePassage(
        evidence_id=evidence_id(doc.document_id, 1, quote), document_id=doc.document_id,
        research_id=f"SYNTHETIC-{tag}", subject_ticker=ticker, subject_type="company",
        pdf_page=1, printed_page="fixture only", section="SYNTHETIC", excerpt_original=quote,
        evidence_kind="other", operational_channel=None, stock_return_direction="unknown",
        interpretation="For merge safety tests only; not investment evidence.",
        quote_verified_claim=False, quote_verification=Verification(),
    )
    result = Catalog((doc,), (passage,))
    result.validate()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--show-catalog", action="store_true", help="Print JSON to stdout; never writes a file")
    args = parser.parse_args()
    imported = read_candidates(args.csv)
    # These associations are supplied research context, not freshly verified holdings.
    batch = attach_holding_context(
        imported.catalog, "XIU.TO", "2026-11-12",
        "team-reported:s3://cascade-s3-bucket/raw/holdings/snapshot=2026-11-15/xiu_holdings.csv",
        {"ATD.TO": "ATD"},
    )
    store = MemoryS3()
    existing = dummy_existing_catalog()
    seed_demo_store(store, existing)
    before = load_active(store)
    after = publish_research_batch(store, batch)
    previous_bytes = store.get_object(Key=before.snapshot_key).body
    print(json.dumps({
        "mode": "OFFLINE RESEARCH SIMULATION — no AWS and no production publication",
        "input_csv_sha256": imported.source_csv_sha256,
        "before": {"documents": len(existing.documents), "passages": len(existing.passages)},
        "after": {"documents": len(after.catalog.documents), "passages": len(after.catalog.passages),
                  "contexts": len(after.catalog.contexts)},
        "existing_synthetic_record_preserved": existing.passages[0] in after.catalog.passages,
        "previous_snapshot_unchanged": previous_bytes == existing.to_bytes(),
        "active_generation": after.generation,
        "ATD_source_verification": imported.catalog.documents[0].source_verification.status,
        "ATD_quote_verification": sorted({p.quote_verification.status for p in imported.catalog.passages}),
        "ATD_stock_return_direction": sorted({p.stock_return_direction for p in imported.catalog.passages}),
        "public_KB_export_supported": False,
        "warnings": imported.warnings,
    }, ensure_ascii=False, indent=2))
    if args.show_catalog:
        print(json.dumps(asdict(after.catalog), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
