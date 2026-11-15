"""Read a user-supplied research CSV without contacting its URLs or source PDFs."""

import csv
from dataclasses import dataclass
import io
from pathlib import Path

from schema import (Catalog, Document, EvidenceContext, EvidencePassage, Verification,
                    ValidationError, context_id, digest, document_id, evidence_id)


FIELDS = (
    "evidence_id", "ticker", "issuer", "document_title", "fiscal_year", "fiscal_year_end",
    "language", "pdf_page", "printed_page", "section", "channel_candidate", "direction",
    "excerpt", "interpretation", "document_file", "sha256", "source_url",
    "url_verified", "quote_verified",
)


@dataclass(frozen=True)
class ImportedBatch:
    catalog: Catalog
    source_csv_sha256: str
    warnings: tuple[str, ...]


def parse_bool(raw):
    if raw not in {"True", "False", "true", "false"}:
        raise ValidationError("Verification claims must be explicit True/False values")
    return raw.lower() == "true"


def read_candidates(path):
    """Preserve quotes and user claims, never promote a CSV assertion to verified."""
    return parse_candidates(Path(path).read_bytes())


def parse_candidates(raw):
    """Parse candidate CSV bytes in memory, including UTF-8 BOM and CRLF records."""
    artifact_hash = digest(raw)  # CSV bytes, NOT a recalculation of the PDF hash.
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
    if reader.fieldnames is None or set(reader.fieldnames) != set(FIELDS) or len(reader.fieldnames) != len(FIELDS):
        raise ValidationError("Unexpected candidate CSV headers")
    documents, passages = {}, []
    research_ids = set()
    try:
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValidationError("Malformed candidate CSV row")
            if row["evidence_id"] in research_ids:
                raise ValidationError("Duplicate research ID")
            research_ids.add(row["evidence_id"])
            url_claim = parse_bool(row["url_verified"])
            quote_claim = parse_bool(row["quote_verified"])
            reported = Verification("reported_verified", "candidate_csv_assertion", artifact_hash)
            unverified = Verification("unverified", "not_independently_checked", artifact_hash)
            source_url = row["source_url"] or None
            doc = Document(
                document_id=document_id(row["sha256"]), sha256=row["sha256"],
                issuer=row["issuer"], document_title=row["document_title"],
                document_file=row["document_file"], language=row["language"],
                fiscal_year=int(row["fiscal_year"]), fiscal_year_end=row["fiscal_year_end"],
                publication_date=None, source_url=source_url, source_url_verified_claim=url_claim,
                source_link_status="unknown" if source_url else "not_supplied",
                issuer_verification=unverified,
                source_verification=reported if url_claim else unverified,
                hash_verification=reported,
            )
            doc.validate()
            if doc.document_id in documents and documents[doc.document_id] != doc:
                raise ValidationError("Conflicting document metadata within candidate CSV")
            documents[doc.document_id] = doc
            page = int(row["pdf_page"])
            passage = EvidencePassage(
                evidence_id=evidence_id(doc.document_id, page, row["excerpt"]),
                document_id=doc.document_id, research_id=row["evidence_id"],
                subject_ticker=row["ticker"], subject_type="company", pdf_page=page,
                printed_page=row["printed_page"], section=row["section"],
                excerpt_original=row["excerpt"], evidence_kind="operational",
                operational_channel=row["channel_candidate"], stock_return_direction=row["direction"],
                interpretation=row["interpretation"], quote_verified_claim=quote_claim,
                quote_verification=reported if quote_claim else unverified,
            )
            passage.validate()
            passages.append(passage)
    except (csv.Error, ValueError) as exc:
        raise ValidationError(f"Candidate CSV rejected: {exc}") from exc
    catalog = Catalog(tuple(documents.values()), tuple(passages))
    catalog.validate()
    return ImportedBatch(catalog, artifact_hash, (
        "Research catalog only: no source PDF was opened or hashed.",
        "quote_verified and url_verified are preserved as supplied claims, not independent checks.",
        "No URL, issuer, publication date, holding membership or statistical effect was verified.",
    ))


def attach_holding_context(catalog, investigation_ticker, holdings_as_of, holdings_source_id, row_ids):
    """Explicit supplied association, never inferred from a company name or quote."""
    catalog.validate()
    contexts = []
    for passage in catalog.passages:
        row_id = row_ids.get(passage.subject_ticker)
        if row_id is None:
            raise ValidationError("A holding row reference is required for every subject")
        args = (passage.evidence_id, investigation_ticker, "holding", passage.subject_ticker,
                holdings_as_of, holdings_source_id, row_id)
        contexts.append(EvidenceContext(context_id(*args), *args))
    result = Catalog(catalog.documents, catalog.passages, catalog.contexts + tuple(contexts))
    result.validate()
    return result
