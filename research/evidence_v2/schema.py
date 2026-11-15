"""Research-only evidence structures. Standard library; no I/O or AWS dependencies."""

from dataclasses import asdict, dataclass
from datetime import date, datetime
import hashlib
import json
import re
from urllib.parse import urlsplit


class ValidationError(ValueError):
    pass


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def document_id(sha256):
    return "doc:sha256:" + sha256


def evidence_id(document, pdf_page, original_quote):
    # Do not normalize spaces, accents, punctuation, or footnote markers.
    return "ev:sha256:" + digest(canonical_bytes([document, pdf_page, original_quote]))


def context_id(evidence, investigation, association, subject, as_of, source, row):
    return "ctx:sha256:" + digest(canonical_bytes(
        [evidence, investigation, association, subject, as_of, source, row]))


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def text(value, name):
    require(isinstance(value, str) and bool(value.strip()), f"{name} must be nonempty text")


def iso_date(value, name, optional=False):
    if optional and value is None:
        return
    require(isinstance(value, str), f"{name} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"Invalid {name}") from exc
    require(parsed.isoformat() == value, f"Invalid {name}")


@dataclass(frozen=True)
class Verification:
    status: str = "unverified"
    method: str | None = None
    source_artifact_sha256: str | None = None
    checked_at: str | None = None
    verified_by: str | None = None

    def validate(self):
        require(self.status in {"unverified", "reported_verified", "verified", "rejected"},
                "Unknown verification status")
        if self.source_artifact_sha256 is not None:
            require(bool(re.fullmatch(r"[0-9a-f]{64}", self.source_artifact_sha256)),
                    "Invalid verification artifact hash")
        if self.method is not None:
            text(self.method, "verification method")
        if self.verified_by is not None:
            text(self.verified_by, "verifier")
        if self.checked_at is not None:
            try:
                stamp = datetime.fromisoformat(self.checked_at.replace("Z", "+00:00"))
            except (AttributeError, ValueError) as exc:
                raise ValidationError("Invalid verification timestamp") from exc
            require(stamp.tzinfo is not None, "Verification timestamp needs a timezone")
        if self.status == "reported_verified":
            require(bool(self.method and self.source_artifact_sha256),
                    "Reported verification needs its assertion source")
        if self.status == "verified":
            require(bool(self.method and self.verified_by and self.checked_at),
                    "Verified status requires method, verifier and timestamp")


@dataclass(frozen=True)
class Document:
    document_id: str
    sha256: str
    issuer: str
    document_title: str
    document_file: str
    language: str
    fiscal_year: int
    fiscal_year_end: str
    publication_date: str | None
    source_url: str | None
    source_url_verified_claim: bool
    source_link_status: str
    issuer_verification: Verification
    source_verification: Verification
    hash_verification: Verification
    doc_type: str = "annual_report"
    s3_key: str | None = None

    def validate(self):
        require(isinstance(self.sha256, str) and bool(re.fullmatch(r"[0-9a-f]{64}", self.sha256)),
                "SHA-256 must contain 64 lowercase hexadecimal characters")
        require(self.document_id == document_id(self.sha256), "Document ID/hash mismatch")
        for name in ("issuer", "document_title", "document_file", "language", "doc_type"):
            text(getattr(self, name), name)
        require(type(self.fiscal_year) is int and 1 <= self.fiscal_year <= 9999,
                "Invalid fiscal year")
        iso_date(self.fiscal_year_end, "fiscal_year_end")
        iso_date(self.publication_date, "publication_date", optional=True)
        require(type(self.source_url_verified_claim) is bool, "URL claim must be a boolean")
        require(self.source_link_status in {"not_supplied", "unknown", "available", "unavailable"},
                "Invalid link status")
        if self.source_url is not None:
            require(isinstance(self.source_url, str), "URL must be text")
            try:
                parsed = urlsplit(self.source_url)
                valid = (parsed.scheme in {"http", "https"} and parsed.hostname
                         and parsed.username is None and parsed.password is None)
            except ValueError:
                valid = False
            require(bool(valid), "Source must be a public HTTP(S) URL without user credentials")
            require(self.source_link_status != "not_supplied", "Supplied URL marked absent")
        else:
            require(not self.source_url_verified_claim, "Cannot claim verification of a missing URL")
            require(self.source_link_status == "not_supplied", "Missing URL must be marked not_supplied")
            require(self.source_verification.status == "unverified", "Missing source URL cannot be verified")
        for verification in (self.issuer_verification, self.source_verification, self.hash_verification):
            require(isinstance(verification, Verification), "Invalid document verification")
            verification.validate()
        if self.s3_key is not None:
            text(self.s3_key, "s3_key")


@dataclass(frozen=True)
class EvidencePassage:
    evidence_id: str
    document_id: str
    research_id: str
    subject_ticker: str
    subject_type: str
    pdf_page: int
    printed_page: str
    section: str
    excerpt_original: str
    evidence_kind: str
    operational_channel: str | None
    stock_return_direction: str
    interpretation: str
    quote_verified_claim: bool
    quote_verification: Verification

    def validate(self):
        require(type(self.pdf_page) is int and self.pdf_page > 0, "PDF page must be a positive integer")
        for name in ("document_id", "research_id", "subject_ticker", "printed_page", "section", "excerpt_original"):
            text(getattr(self, name), name)
        require(self.subject_type in {"company", "etf", "macro"}, "Invalid subject type")
        require(self.evidence_kind in {"operational", "stock_return_statement", "other"},
                "Invalid evidence kind; statistics belong to a separate model")
        require(self.stock_return_direction in {"positive", "negative", "mixed", "unknown"},
                "Invalid stock return direction")
        if self.evidence_kind == "operational":
            text(self.operational_channel, "operational_channel")
            require(self.stock_return_direction == "unknown",
                    "Operational exposure cannot establish a stock-return direction")
        require(isinstance(self.interpretation, str), "Interpretation must be separate text")
        require(type(self.quote_verified_claim) is bool, "Quote claim must be a boolean")
        require(isinstance(self.quote_verification, Verification), "Invalid quote verification")
        self.quote_verification.validate()
        require(self.evidence_id == evidence_id(self.document_id, self.pdf_page, self.excerpt_original),
                "Evidence ID/content mismatch")


@dataclass(frozen=True)
class EvidenceContext:
    context_id: str
    evidence_id: str
    investigation_ticker: str
    association_type: str
    subject_ticker: str
    holdings_as_of: str | None = None
    holdings_source_id: str | None = None
    holding_row_id: str | None = None

    def validate(self):
        for name in ("evidence_id", "investigation_ticker", "subject_ticker"):
            text(getattr(self, name), name)
        require(self.association_type in {"holding", "direct_etf"}, "Invalid association type")
        if self.association_type == "holding":
            iso_date(self.holdings_as_of, "holdings_as_of")
            text(self.holdings_source_id, "holdings_source_id")
            text(self.holding_row_id, "holding_row_id")
            require(self.subject_ticker != self.investigation_ticker, "Holding is not the ETF itself")
        else:
            require(self.subject_ticker == self.investigation_ticker, "Direct ETF evidence must concern that ETF")
            require(all(value is None for value in
                        (self.holdings_as_of, self.holdings_source_id, self.holding_row_id)),
                    "Direct ETF evidence must not invent a holding")
        expected = context_id(self.evidence_id, self.investigation_ticker, self.association_type,
                              self.subject_ticker, self.holdings_as_of, self.holdings_source_id,
                              self.holding_row_id)
        require(self.context_id == expected, "Context ID/content mismatch")


@dataclass(frozen=True)
class Catalog:
    documents: tuple[Document, ...] = ()
    passages: tuple[EvidencePassage, ...] = ()
    contexts: tuple[EvidenceContext, ...] = ()
    schema_version: int = 2
    catalog_kind: str = "research_only"

    def validate(self):
        require(type(self.schema_version) is int and self.schema_version == 2, "Unsupported schema version")
        require(self.catalog_kind == "research_only", "This POC only accepts research catalogs")
        for rows, cls, key in ((self.documents, Document, "document_id"),
                               (self.passages, EvidencePassage, "evidence_id"),
                               (self.contexts, EvidenceContext, "context_id")):
            require(isinstance(rows, tuple), "Catalog collections must be immutable tuples")
            seen = set()
            for row in rows:
                require(isinstance(row, cls), "Wrong catalog record type")
                row.validate()
                identity = getattr(row, key)
                require(identity not in seen, f"Duplicate {key}")
                seen.add(identity)
        documents = {row.document_id: row for row in self.documents}
        passages = {row.evidence_id: row for row in self.passages}
        for passage in self.passages:
            require(passage.document_id in documents, "Passage references a missing document")
        for context in self.contexts:
            require(context.evidence_id in passages, "Context references a missing passage")
            passage = passages[context.evidence_id]
            require(context.subject_ticker == passage.subject_ticker, "Context changes evidence subject")
            if context.association_type == "direct_etf":
                require(passage.subject_type == "etf", "Company evidence cannot become direct ETF evidence")

    def to_bytes(self):
        self.validate()
        data = asdict(self)
        for name, key in (("documents", "document_id"), ("passages", "evidence_id"),
                          ("contexts", "context_id")):
            data[name] = sorted(data[name], key=lambda row: row[key])
        return canonical_bytes(data)

    @classmethod
    def from_bytes(cls, raw):
        try:
            data = json.loads(raw)
            require(set(data) == {"schema_version", "catalog_kind", "documents", "passages", "contexts"},
                    "Invalid catalog envelope")
            require(all(isinstance(data[k], list) for k in ("documents", "passages", "contexts")),
                    "Invalid catalog collections")
            documents = []
            for item in data["documents"]:
                row = dict(item)
                for name in ("issuer_verification", "source_verification", "hash_verification"):
                    row[name] = Verification(**row[name])
                documents.append(Document(**row))
            passages = []
            for item in data["passages"]:
                row = dict(item)
                row["quote_verification"] = Verification(**row["quote_verification"])
                passages.append(EvidencePassage(**row))
            result = cls(tuple(documents), tuple(passages),
                         tuple(EvidenceContext(**row) for row in data["contexts"]),
                         data["schema_version"], data["catalog_kind"])
            result.validate()
            return result
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ValidationError("Invalid research catalog; refusing to treat it as empty") from exc
