"""Resolve company evidence through a verified local dated holding, never as ETF evidence."""
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from schema import EvidenceContext, ValidationError, context_id, digest, require
from xiu_holdings import XIU_DATE, confirmed_holding


def resolve_constituent_evidence(snapshot, catalog, document_paths, *,
                                 constituents=("ATD.TO", "CNR.TO"), acquisition=None,
                                 checked_at=None):
    catalog.validate()
    require(snapshot.investigation_ticker == "XIU.TO" and snapshot.as_of == XIU_DATE,
            "Resolver requires XIU holdings officially dated 2026-11-12")
    require(bool(constituents) and len(set(constituents)) == len(constituents), "Invalid constituent scope")
    holdings = {ticker: confirmed_holding(snapshot, ticker) for ticker in constituents}
    selected = [p for p in catalog.passages if p.subject_ticker in holdings]
    require(all(any(p.subject_ticker == t for p in selected) for t in constituents),
            "Constituent evidence missing; no fallback to another company")
    require(all(p.subject_type == "company" and p.evidence_kind == "operational"
                and p.stock_return_direction == "unknown" for p in selected),
            "Resolver only accepts operational company evidence with unknown stock direction")
    stamp = checked_at or datetime.now(timezone.utc).isoformat()
    sources = {d.document_id: d for d in catalog.documents}
    documents = {}
    for identity in sorted({p.document_id for p in selected}):
        require(identity in document_paths, "Source PDF path missing")
        try:
            raw = Path(document_paths[identity]).read_bytes()
        except OSError as exc:
            raise ValidationError("Source PDF missing or unreadable") from exc
        doc = sources[identity]
        require(digest(raw) == doc.sha256, "Source document hash mismatch")
        require(raw.startswith(b"%PDF-"), "Source file is not a PDF")
        documents[identity] = {**asdict(doc), "local_file": str(Path(document_paths[identity]).resolve()),
            "local_file_verification": {"status": "verified", "method": "local_sha256_comparison",
                "checked_at": stamp, "sha256": digest(raw), "scope": "bytes_only_not_financial_claims"},
            "publication_date_verification": "unverified",
            "acquisition": (acquisition or {}).get(identity)}
    rows = []
    for passage in sorted(selected, key=lambda p: (p.subject_ticker, p.research_id)):
        h = holdings[passage.subject_ticker]
        args = (passage.evidence_id, "XIU.TO", "holding", passage.subject_ticker,
                snapshot.as_of, snapshot.source_id, h.row_id)
        context = EvidenceContext(context_id(*args), *args)
        context.validate()
        source = documents[passage.document_id]
        rows.append({**asdict(passage), "ticker": passage.subject_ticker,
            "holding_ticker_original": h.ticker_original,
            "holding_weight_pct": float(h.weight_pct), "holding_weight_pct_original": str(h.weight_pct),
            "document_sha256": source["sha256"], "context": asdict(context),
            "verification": {"holding_membership": "verified_in_local_snapshot",
                "document_bytes": "verified", "official_provenance": source["source_verification"],
                "issuer": source["issuer_verification"], "quote": asdict(passage.quote_verification),
                "page_reference": "reported_in_research_register_not_reextracted",
                "interpretation": "not_validated_by_resolver"}})
    total = sum((h.weight_pct for h in snapshot.rows), Decimal(0))
    scoped = sum((h.weight_pct for h in holdings.values()), Decimal(0))
    return {
        "schema_version": 2, "catalog_kind": "research_only", "mode": "local_read_only",
        "investigation_ticker": "XIU.TO", "resolved_at": stamp,
        "holdings_snapshot": {"as_of": snapshot.as_of, "source_id": snapshot.source_id,
            "sha256": snapshot.sha256, "membership_basis": "provided_official_snapshot_hashed_locally",
            "s3_verification": "not_checked", "row_count": len(snapshot.rows),
            "total_displayed_weight_pct": float(total), "weights_renormalized": False},
        "scope": {"constituents": list(constituents), "document_count": len(documents),
            "passage_count": len(rows), "constituent_weight_pct": float(scoped),
            "weight_meaning": "holdings_with_selected_candidates_not_statistical_coverage",
            "other_holdings": "outside_this_resolver_scope"},
        "holdings": [{"ticker": ticker, **asdict(h), "weight_pct": float(h.weight_pct),
                      "weight_pct_original": str(h.weight_pct)} for ticker, h in holdings.items()],
        "documents": list(documents.values()), "passages": rows,
        "statistical_relationships": {"status": "not_computed", "benchmark": "Brent",
            "beta": None, "contributions": [],
            "reason": "Operational statements do not establish statistical sensitivity or stock-return direction."},
        "limitations": ["Local source checks do not verify current S3 or online availability.",
            "Reported quote/provenance checks are preserved, not promoted to independent verification.",
            "CN-2025-01 is a table heading requiring context; ATD footnotes and all interpretations need review.",
            "No evidence is published or reassigned directly to XIU."],
    }
