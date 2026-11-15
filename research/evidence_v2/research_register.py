"""Read the existing XLSX evidence register using only the standard library.

Never execute formulas, instructions in cells, URLs or the production pipeline.
Acquisition receipts are historical observations, not new online verification.
"""
import io
from pathlib import Path, PurePosixPath
import xml.etree.ElementTree as ET
import zipfile

from schema import (Catalog, Document, EvidencePassage, Verification, ValidationError,
                    digest, document_id, evidence_id, require)

REGISTER_SHA256 = "d12abd3a0da045977ec78f232b986721992c87f884c703fd86a6245b14287214"
S = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
HEADERS = ("Research ID", "Ticker", "Issuer", "Document", "PDF page", "Printed page", "Section",
           "Exact excerpt", "Operational channel", "Stock return direction", "Validation status",
           "SHA256", "Original PDF URL")
SPECS = {
    "ATD.TO": ("ATD_2026_FR", 2026, "2026-04-26", "fr"),
    "CNR.TO": ("CNR_2025_EN", 2025, "2025-12-31", "en"),
}


def read_register_rows(path, expected_sha256=REGISTER_SHA256):
    try:
        raw = Path(path).read_bytes()
        require(digest(raw) == expected_sha256, "Research register hash mismatch")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            require(sum(i.file_size for i in archive.infolist()) < 10_000_000, "Register exceeds size limit")
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            sheets = [s for s in workbook.findall("s:sheets/s:sheet", S)
                      if s.get("name") == "EVIDENCE CANDIDATES"]
            require(len(sheets) == 1, "Evidence worksheet missing or ambiguous")
            rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            matches = [r for r in rels if r.get("Id") == sheets[0].get("{" + REL + "}id")]
            require(len(matches) == 1 and matches[0].get("TargetMode") != "External", "Invalid sheet target")
            target = matches[0].get("Target", "")
            require(".." not in PurePosixPath(target).parts, "Invalid worksheet path")
            target = target.lstrip("/") if target.startswith("/") else "xl/" + target
            strings = []
            if "xl/sharedStrings.xml" in archive.namelist():
                strings = ["".join(x.itertext()) for x in
                           ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("s:si", S)]
            rows = []
            for row in ET.fromstring(archive.read(target)).findall(".//s:row", S):
                cells = {}
                for cell in row.findall("s:c", S):
                    require(cell.find("s:f", S) is None, "Formulas are not accepted as evidence")
                    column = "".join(ch for ch in cell.get("r", "") if ch.isalpha())
                    number = 0
                    for ch in column:
                        number = number * 26 + ord(ch) - ord("A") + 1
                    require(1 <= number <= len(HEADERS) and number not in cells, "Invalid worksheet column")
                    value = "".join(cell.itertext())
                    cells[number] = strings[int(value)] if cell.get("t") == "s" else value
                rows.append([cells.get(i, "") for i in range(1, len(HEADERS) + 1)])
            require(bool(rows) and tuple(rows[0]) == HEADERS, "Unexpected evidence register columns")
            return [dict(zip(HEADERS, row)) for row in rows[1:] if any(row)], digest(raw)
    except (OSError, zipfile.BadZipFile, KeyError, IndexError, ValueError, ET.ParseError) as exc:
        raise ValidationError(f"Cannot read local research register: {exc}") from exc


def build_register_catalog(rows, register_hash, acquisition_manifest, manifest_hash, acquisition_root):
    documents, passages, paths, observations = {}, [], {}, {}
    require(bool(rows), "Empty evidence register")
    for row in rows:
        ticker = row["Ticker"]
        require(ticker in SPECS, "Unmatched evidence ticker in register")
        source_id, year, year_end, language = SPECS[ticker]
        matches = [e for e in acquisition_manifest["entries"] if e["id"] == source_id]
        require(len(matches) == 1, "Acquisition receipt missing or ambiguous")
        entry = matches[0]
        require(entry["ticker"] == ticker and entry["sha256"] == row["SHA256"],
                "Document-hash or ticker mismatch between register and receipt")
        require(entry["issuer"] == row["Issuer"] and entry["title"] == row["Document"],
                "Document identity conflict between register and receipt")
        require(entry["fiscal_year_end"] == year_end and entry["reporting_period"] == f"FY{year}",
                "Document fiscal period conflict")
        require(entry["download_status"] == "downloaded" and entry["http_receipt"]["http_status"] == 200,
                "Source document has no successful acquisition receipt")
        path = (Path(acquisition_root) / entry["local_file"]).resolve()
        require(path.is_relative_to(Path(acquisition_root).resolve()), "Document path escapes acquisition root")
        reported = Verification("reported_verified", "research_register_assertion", register_hash)
        prior = Verification("reported_verified", "historical_acquisition_receipt", manifest_hash)
        doc = Document(document_id(row["SHA256"]), row["SHA256"], row["Issuer"], row["Document"],
                       path.name, language, year, year_end, None, entry["official_url"], False, "unknown",
                       prior, prior, reported)
        if doc.document_id in documents:
            require(documents[doc.document_id] == doc, "Conflicting document metadata")
        documents[doc.document_id] = doc
        paths[doc.document_id] = path
        observations[doc.document_id] = {
            "retrieved_at": entry["retrieved_at"], "original_url": entry["official_url"],
            "final_url": entry["http_receipt"]["final_url"],
            "download_status_at_retrieval": entry["download_status"],
            "current_link_availability": "not_checked",
            "manifest_sha256": manifest_hash,
            "research_source_url": row["Original PDF URL"] or None,
            "page_count_from_receipt": entry["content_validation"]["page_count"],
        }
        quote_claim = row["Validation status"].startswith("Local quote checked;")
        page = int(row["PDF page"])
        require(0 < page <= observations[doc.document_id]["page_count_from_receipt"], "PDF page outside document")
        require(row["Stock return direction"] == "unknown", "Operational evidence cannot assert a stock direction")
        passages.append(EvidencePassage(
            evidence_id(doc.document_id, page, row["Exact excerpt"]), doc.document_id, row["Research ID"],
            ticker, "company", page, row["Printed page"], row["Section"], row["Exact excerpt"],
            "operational", row["Operational channel"], "unknown", "", quote_claim,
            reported if quote_claim else Verification()))
    require(len({p.research_id for p in passages}) == len(passages), "Duplicate research passage ID")
    catalog = Catalog(tuple(documents.values()), tuple(passages))
    catalog.validate()
    return catalog, paths, observations
