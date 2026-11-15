"""XIU evidence resolver extended to five documented constituents: ATD, CNR, RY, CNQ, CP.

    python3 -B research/evidence_v2/xiu_resolver_5.py                      # print the resolution
    python3 -B research/evidence_v2/xiu_resolver_5.py --output xiu_resolution_5_companies.json

Isolated research code. It reuses the existing modules unchanged:
  - the 12 ATD/CNR passages come from the original `resolve_constituent_evidence` path (register + receipts),
    so their identifiers, quotations and verification records are exactly those of xiu_resolution.json;
  - the 23 RBC/CNQ/CPKC passages are read with `import_candidates.parse_candidates` from the verified batch CSVs;
  - holdings come from `xiu_holdings.read_holdings` (hash- and date-checked snapshot of 2026-11-12).
New code only adds the three reviewed ticker mappings, cross-batch duplicate checks, weight checks, and the
separate statistical-status block. Local files only: no network, no AWS, no production pipeline.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

from catalog import merge_catalog
from constituent_resolver import resolve_constituent_evidence
from import_candidates import parse_candidates
from research_register import build_register_catalog, read_register_rows
from schema import EvidenceContext, ValidationError, context_id, digest, require
from inputs import load_inputs
from research_register import REGISTER_SHA256
from xiu_holdings import ALIASES, XIU_DATE, XIU_SHA256, read_holdings

ROOT = Path(__file__).resolve().parent
ACQUISITIONS = ROOT.parent / "source_documents"
RUN = ACQUISITIONS / "runs/20261115T131702Z_d4fbb4fa"

# Reviewed mappings: evidence ticker -> (holding ticker in the iShares CSV, exact holding name in that CSV).
# The ATD/CNR entries must agree with xiu_holdings.ALIASES (checked below); no suffix heuristics.
MAPPINGS = {
    "ATD.TO": ("ATD", "ALIMENTATION COUCHE TARD INC"),
    "CNR.TO": ("CNR", "CANADIAN NATIONAL RAILWAY"),
    "RY.TO": ("RY", "ROYAL BANK OF CANADA"),
    "CNQ.TO": ("CNQ", "CANADIAN NATURAL RESOURCES LTD"),
    "CP.TO": ("CP", "CANADIAN PACIFIC KANSAS CITY"),
}
REGISTER_TICKERS = ("ATD.TO", "CNR.TO")
BATCH_FILES = {  # ticker -> (candidate CSV, verification sidecar, acquisition receipt id)
    "RY.TO": ("candidates_rbc_2025.csv", "candidates_rbc_2025.verification.json", "RBC_2025_EN"),
    "CNQ.TO": ("candidates_cnq_2025.csv", "candidates_cnq_2025.verification.json", "CNQ_2025_EN"),
    "CP.TO": ("candidates_cpkc_2025.csv", "candidates_cpkc_2025.verification.json", "CPKC_2025_EN"),
}
# Membership of the statistical model universe (docs/data_contract.md). Status only: no beta is copied here.
MODEL_UNIVERSE = {"ATD.TO": "core", "RY.TO": "core", "CNR.TO": "extra", "CNQ.TO": "extra", "CP.TO": None}
WEIGHT_TOTAL_TOLERANCE = Decimal("0.5")  # displayed weights may round (100.02); beyond this they are inconsistent


def validate_mapping(snapshot, ticker):
    """Return the single holding row for a reviewed mapping; reject missing, ambiguous or mismatched rows."""
    require(ticker in MAPPINGS, f"No reviewed holding mapping for {ticker}; no automatic alias inference")
    holding_ticker, name = MAPPINGS[ticker]
    by_ticker = [r for r in snapshot.rows if r.ticker_original == holding_ticker]
    require(len(by_ticker) == 1, f"{ticker}: holding {holding_ticker} is %s in the snapshot"
            % ("missing" if not by_ticker else "ambiguous (%d rows)" % len(by_ticker)))
    row = by_ticker[0]
    require(row.company_name == name, f"{ticker}: holding name {row.company_name!r} != reviewed {name!r}")
    same_name = [r for r in snapshot.rows if r.company_name == name]
    require(len(same_name) == 1, f"{ticker}: {name} appears on several rows (share classes?); ambiguous")
    require(row.asset_class == "Equity" and row.exchange == "Toronto Stock Exchange" and row.currency == "CAD",
            f"{ticker}: holding is not a CAD TSX equity")
    return row


def check_weights(snapshot, rows):
    total = sum((r.weight_pct for r in snapshot.rows), Decimal(0))
    require(abs(total - Decimal(100)) <= WEIGHT_TOTAL_TOLERANCE,
            f"Inconsistent holdings weights: displayed total {total}% is not about 100%")
    documented = sum((r.weight_pct for r in rows.values()), Decimal(0))
    require(documented <= total, "Documented weight exceeds the snapshot total")
    return total, documented


def load_batch(ticker):
    csv_name, sidecar_name, receipt_id = BATCH_FILES[ticker]
    raw = (ROOT / csv_name).read_bytes()
    batch = parse_candidates(raw)
    sidecar = json.loads((ROOT / sidecar_name).read_text())
    receipt = json.loads((RUN / f"{receipt_id}.receipt.json").read_text())
    require({p.subject_ticker for p in batch.catalog.passages} == {ticker}, f"{csv_name} is not only {ticker}")
    require(sidecar["document"]["sha256"] == receipt["sha256"] == batch.catalog.documents[0].sha256,
            f"{ticker}: document hash differs between CSV, sidecar and receipt")
    checks = {c["evidence_id"]: c for c in sidecar["candidates"]}
    require(set(checks) == {p.evidence_id for p in batch.catalog.passages}, f"{ticker}: sidecar/CSV mismatch")
    return batch, sidecar, receipt, digest(raw)


def check_unique(passage_groups):
    """Reject duplicate research IDs or evidence IDs across all sources before any merge."""
    research, evidence = {}, {}
    for source, passages in passage_groups.items():
        for p in passages:
            require(p.research_id not in research, f"Duplicate research ID {p.research_id} ({research.get(p.research_id)} and {source})")
            require(p.evidence_id not in evidence, f"Duplicate evidence ID for {p.research_id} ({evidence.get(p.evidence_id)} and {source})")
            research[p.research_id], evidence[p.evidence_id] = source, source


def resolve_five(snapshot, register_catalog, register_paths, register_observations, batches, *,
                 review=None, checked_at=None):
    stamp = checked_at or datetime.now(timezone.utc).isoformat()
    require(snapshot.investigation_ticker == "XIU.TO" and snapshot.as_of == XIU_DATE,
            f"Stale or wrong holdings snapshot: requires XIU dated {XIU_DATE}, got {snapshot.as_of}")
    for t in REGISTER_TICKERS:
        require(ALIASES.get(t) == MAPPINGS[t][0], f"{t}: mapping disagrees with the original resolver")
    rows = {t: validate_mapping(snapshot, t) for t in MAPPINGS}
    total, documented = check_weights(snapshot, rows)
    check_unique({"research_register": register_catalog.passages,
                  **{t: b[0].catalog.passages for t, b in batches.items()}})
    merged = register_catalog
    for batch, *_ in batches.values():
        merged = merge_catalog(merged, batch.catalog)
    require(len(merged.passages) == len(register_catalog.passages) + sum(len(b[0].catalog.passages) for b in batches.values()),
            "Passages were collapsed during merge")

    # 1. The original twelve, through the original code path (exact preservation).
    original = resolve_constituent_evidence(snapshot, register_catalog, register_paths, constituents=REGISTER_TICKERS,
                                            acquisition=register_observations, checked_at=stamp)
    documents = [{**d, "evidence_batch": "research_register_2026-11-15",
                  "metadata_review": (review or {}).get(Path(d["document_file"]).name.rsplit("_", 1)[0])}
                 for d in original["documents"]]
    passages = [{**p, "evidence_batch": "research_register_2026-11-15"} for p in original["passages"]]

    # 2. The 23 batch passages, same row shape, with their own (unpromoted) verification records.
    for ticker, (batch, sidecar, receipt, csv_hash) in batches.items():
        doc = batch.catalog.documents[0]
        path = (ACQUISITIONS / receipt["local_file"]).resolve()
        require(path.is_relative_to(ACQUISITIONS.resolve()), "Document path escapes acquisition root")
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ValidationError(f"{ticker}: source PDF missing or unreadable") from exc
        require(digest(raw) == doc.sha256 and raw.startswith(b"%PDF-"), f"{ticker}: source PDF hash mismatch")
        provenance = sidecar["document"]
        documents.append({**asdict(doc), "local_file": str(path),
            "local_file_verification": {"status": "verified", "method": "local_sha256_comparison",
                "checked_at": stamp, "sha256": digest(raw), "scope": "bytes_only_not_financial_claims"},
            "publication_date_verification": "unverified",
            "acquisition": {"retrieved_at": receipt["retrieved_at"], "original_url": receipt["official_url"],
                "final_url": receipt["http_receipt"]["final_url"], "landing_url": receipt["landing_url"],
                "current_link_availability": "not_checked",
                "page_count_from_receipt": receipt["content_validation"]["page_count"]},
            "provenance_status": provenance["provenance_status"], "provenance_note": provenance["provenance_note"],
            "candidate_csv_sha256": csv_hash, "evidence_batch": "oil_batch_2025",
            "metadata_review": (review or {}).get(receipt["id"])})
        h = rows[ticker]
        checks = {c["evidence_id"]: c for c in sidecar["candidates"]}
        for p in sorted(batch.catalog.passages, key=lambda p: p.research_id):
            args = (p.evidence_id, "XIU.TO", "holding", ticker, snapshot.as_of, snapshot.source_id, h.row_id)
            context = EvidenceContext(context_id(*args), *args)
            context.validate()
            check = checks[p.evidence_id]
            passages.append({**asdict(p), "ticker": ticker, "holding_ticker_original": h.ticker_original,
                "holding_weight_pct": float(h.weight_pct), "holding_weight_pct_original": str(h.weight_pct),
                "document_sha256": doc.sha256, "context": asdict(context), "evidence_batch": "oil_batch_2025",
                "verification": {"holding_membership": "verified_in_local_snapshot", "document_bytes": "verified",
                    "official_provenance": asdict(doc.source_verification),
                    "provenance_status": provenance["provenance_status"],
                    "issuer": asdict(doc.issuer_verification), "quote": asdict(p.quote_verification),
                    "quote_pdf_text_check": {**check["quote_verification"],
                        "match_method": check["verification"]["match_method"],
                        "scope": "PDF text layer at batch build (oil_batch_2025); not re-run by this resolver"},
                    "page_reference": "reextracted_pdfkit_text_layer_in_oil_batch_2025",
                    "interpretation": "not_validated_by_resolver"}})

    by_ticker = {t: [p for p in passages if p["ticker"] == t] for t in MAPPINGS}
    require(all(by_ticker.values()), "A mapped constituent has no evidence; no fallback to another company")
    for p in passages:  # every passage carries exactly its holding's displayed weight
        require(p["holding_weight_pct_original"] == str(rows[p["ticker"]].weight_pct), "Inconsistent passage weight")
    return {
        "schema_version": 2, "catalog_kind": "research_only", "mode": "local_read_only",
        "investigation_ticker": "XIU.TO", "resolved_at": stamp,
        "holdings_snapshot": {"as_of": snapshot.as_of, "source_id": snapshot.source_id, "sha256": snapshot.sha256,
            "membership_basis": "provided_official_snapshot_hashed_locally", "s3_verification": "not_checked",
            "row_count": len(snapshot.rows), "total_displayed_weight_pct": str(total), "weights_renormalized": False},
        "scope": {"constituents": list(MAPPINGS), "document_count": len(documents), "passage_count": len(passages),
            "distinct_holdings_count": len(rows), "documented_holding_weight_pct": str(documented),
            "weight_meaning": "Sum of the displayed XIU weights of the holdings that have evidence. It is NOT "
                              "statistical beta coverage, attribution or a share of XIU's oil sensitivity.",
            "passages_by_ticker": {t: len(v) for t, v in by_ticker.items()},
            "other_holdings": "outside_this_resolver_scope"},
        "holdings": [{"ticker": t, **asdict(h), "weight_pct": float(h.weight_pct),
                      "weight_pct_original": str(h.weight_pct), "mapping_review": "explicit_reviewed_mapping"}
                     for t, h in rows.items()],
        "documents": documents, "passages": passages,
        "statistical_relationships": {
            "benchmark": "Brent", "status": "not_computed_by_resolver",
            "separation": "Operational passages above never carry a beta, and no beta here is derived from them.",
            "by_ticker": {t: ({"model_universe": u, "beta": None,
                               "status": "legacy_saved_output_only_must_be_recomputed_on_current_stats_code"}
                              if u else {"model_universe": None, "beta": None,
                                         "status": "no_validated_beta_ticker_not_in_model_universe"})
                          for t, u in MODEL_UNIVERSE.items()}},
        "limitations": [
            "Local source checks do not verify current S3 or online availability.",
            "Quote/provenance records are preserved as found; none is promoted to a stronger status here.",
            "CPKC provenance is pending: the issuer-to-CDN link for its PDF is not yet established.",
            "Interpretations are the research team's and are not validated by this resolver.",
            "No evidence is published, reassigned directly to XIU, or used as a statistical estimate.",
        ],
    }


def resolve_local_inputs(config=None):
    """Inputs come from the explicit config (see inputs.py); hashes must equal the reviewed ones."""
    inputs = load_inputs(config)
    require(inputs.holdings.sha256 == XIU_SHA256, "Config names a holdings file other than the reviewed snapshot")
    require(inputs.register.sha256 == REGISTER_SHA256, "Config names a register other than the reviewed one")
    require(inputs.holdings.meta.get("as_of") == XIU_DATE, f"Config holdings date must be {XIU_DATE}")
    holdings, register = inputs.holdings.path, inputs.register.path
    snapshot = read_holdings(holdings)
    reg_rows, register_hash = read_register_rows(register)
    manifest_raw = (RUN / "manifest.json").read_bytes()
    catalog, paths, observations = build_register_catalog(
        reg_rows, register_hash, json.loads(manifest_raw), digest(manifest_raw), ACQUISITIONS)
    require(len(catalog.passages) == 12, "Expected the reviewed twelve-candidate register")
    review = {r["source_id"]: {"status": r["metadata_review_status"], "notes": r["notes"],
                               "quote_verification_status": r["quote_verification_status"]}
              for r in json.loads((RUN / "metadata_review.json").read_text())["reviews"]}
    batches = {t: load_batch(t) for t in BATCH_FILES}
    result = resolve_five(snapshot, catalog, paths, observations, batches, review=review)
    result["inputs"] = {"config": str(inputs.config_path), "holdings_source": inputs.holdings.meta.get("source"),
                        "holdings_file": str(Path(holdings).resolve()), "register_file": str(Path(register).resolve()),
                        "register_sha256": register_hash, "acquisition_manifest_sha256": digest(manifest_raw),
                        "candidate_csv_sha256": {t: b[3] for t, b in batches.items()}}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--inputs", type=Path, help="input config JSON (default: $CASCADE_RESEARCH_INPUTS or local_inputs.json)")
    parser.add_argument("--output", type=Path, help="NEW JSON file inside research/evidence_v2 (never overwritten)")
    args = parser.parse_args()
    try:
        result = resolve_local_inputs(args.inputs)
        text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output:
            target = (ROOT / args.output).resolve() if not args.output.is_absolute() else args.output.resolve()
            require(target.is_relative_to(ROOT), "Output must remain inside research/evidence_v2")
            with target.open("x", encoding="utf-8") as out:
                out.write(text)
            print(json.dumps({"output": str(target), **result["scope"]}, ensure_ascii=False, indent=2))
        else:
            print(text, end="")
    except (ValidationError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"Local resolution stopped: {exc}\n")


if __name__ == "__main__":
    main()
