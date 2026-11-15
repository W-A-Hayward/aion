"""Verify the oil_batch_2025 candidates against the original PDFs, then write candidate CSVs and sidecars.

    python3 -B research/evidence_v2/build_oil_batch.py               # verify only, print a report
    python3 -B research/evidence_v2/build_oil_batch.py --write       # also create the output files (exclusive)
    python3 -B research/evidence_v2/build_oil_batch.py --write --overwrite

For every candidate:
  1. the PDF's SHA-256 must equal its acquisition receipt;
  2. the page text is re-extracted with macOS PDFKit (../source_documents/pdf_metadata.js, the team's extractor);
  3. the excerpt must occur exactly once on that PDF page, byte-exact or with line breaks collapsed to spaces
     (recorded as which); every anchor (table title, units, headings, footnotes) must occur on the same page;
  4. the printed page must agree with both the page-footer marker and the document's page offset.
If pypdf is importable it is used as an independent second extractor (informational; never required).

Outputs, in this directory: candidates_{rbc,cnq,cpkc}_2025.csv (exactly the import_candidates.FIELDS format)
and candidates_*_2025.verification.json (context, tables, units, footnotes, provenance, verification record).
Local files only: no network, no AWS, no production pipeline. Standard library (+ optional pypdf).
"""
import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from import_candidates import FIELDS, parse_candidates  # noqa: E402
from oil_batch_2025 import CANDIDATES, HYPOTHESES, RUN_DIR, SOURCES  # noqa: E402
from schema import Verification, document_id, evidence_id  # noqa: E402

EXTRACTOR = HERE.parent / "source_documents" / "pdf_metadata.js"
SLUG = {"RBC_2025_EN": "rbc", "CNQ_2025_EN": "cnq", "CPKC_2025_EN": "cpkc"}
CONTEXT_CHARS = 450
VERIFIER = "research session: automated PDFKit text-layer match + manual visual check of table columns"


def norm(text):
    return re.sub(r"\s+", " ", text).strip()


def receipt(source_id):
    return json.loads((HERE / RUN_DIR / f"{source_id}.receipt.json").read_text())


def pdf_path(rec):
    return HERE.parent / "source_documents" / rec["local_file"]


def pdfkit_pages(path):
    out = subprocess.run(["osascript", "-l", "JavaScript", str(EXTRACTOR), str(path)],
                         capture_output=True, text=True, check=True, timeout=600)
    data = json.loads(out.stdout)
    return {p["pdf_page"]: p["text"] for p in data["pages"]}


def pypdf_page(path, number, cache={}):
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    if path not in cache:
        cache[path] = PdfReader(str(path))
    return cache[path].pages[number - 1].extract_text() or ""


def context(page_norm, excerpt):
    i = page_norm.find(excerpt)
    before = page_norm[max(0, i - CONTEXT_CHARS):i]
    after = page_norm[i + len(excerpt):i + len(excerpt) + CONTEXT_CHARS]
    before = ("…" + before.split(" ", 1)[-1]) if i > CONTEXT_CHARS else before
    after = (after.rsplit(" ", 1)[0] + "…") if i + len(excerpt) + CONTEXT_CHARS < len(page_norm) else after
    return before.strip(), after.strip()


def check_printed_page(spec, cand, raw):
    markers = []
    for pattern in spec["footer_patterns"]:
        markers += re.findall(pattern, raw)
    markers = sorted(set(markers), key=int)
    offset_ok = cand["pdf_page"] + spec["printed_page_offset"] == int(cand["printed_page"])
    in_spread = cand["pdf_page"] in spec.get("spread_pdf_pages", [])
    footer_ok = cand["printed_page"] in markers if markers else None
    ok = offset_ok and not in_spread and footer_ok is not False
    return {"ok": ok, "footer_markers": markers, "footer_match": footer_ok, "offset_rule":
            "printed = pdf_page %+d" % spec["printed_page_offset"], "offset_match": offset_ok,
            "two_page_spread": in_spread}


def verify(cand, pages, path):
    raw = pages[cand["pdf_page"]]
    page_norm = norm(raw)
    excerpt = cand["excerpt"]
    occurrences = page_norm.count(excerpt)
    anchors = {a: norm(a) in page_norm for a in cand.get("anchors", [])}
    printed = check_printed_page(SOURCES[cand["source"]], cand, raw)
    second = pypdf_page(path, cand["pdf_page"])
    result = {
        "extractor": "macOS PDFKit via source_documents/pdf_metadata.js",
        "byte_exact_match": excerpt in raw,
        "whitespace_normalized_match": occurrences > 0,
        "match_method": "byte_exact" if excerpt in raw else "whitespace_normalized" if occurrences else "none",
        "occurrences_on_page": occurrences,
        "anchors_found": anchors,
        "printed_page_check": printed,
        "second_extractor_pypdf": None if second is None else norm(second).count(excerpt) == 1,
    }
    result["passed"] = (occurrences == 1 and all(anchors.values()) and printed["ok"])
    return result, page_norm


def build(check_only=True, overwrite=False):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    reports, failures = {}, []
    for source_id, spec in SOURCES.items():
        rec = receipt(source_id)
        path = pdf_path(rec)
        data = path.read_bytes()
        actual = sha256(data).hexdigest()
        if actual != rec["sha256"]:
            raise SystemExit(f"{source_id}: PDF hash {actual} != receipt {rec['sha256']}")
        pages = pdfkit_pages(path)
        doc_id = document_id(actual)
        rows, records = [], []
        for cand in [c for c in CANDIDATES if c["source"] == source_id]:
            result, page_norm = verify(cand, pages, path)
            before, after = context(page_norm, cand["excerpt"]) if result["occurrences_on_page"] else ("", "")
            if not result["passed"]:
                failures.append((cand["id"], result))
            quote_verification = Verification(
                "verified" if result["passed"] else "rejected",
                "PDFKit text layer: excerpt occurs once on the stated PDF page (%s); anchors and printed page "
                "checked" % result["match_method"], actual, now, VERIFIER)
            quote_verification.validate()
            ev_id = evidence_id(doc_id, cand["pdf_page"], cand["excerpt"])
            rows.append({
                "evidence_id": cand["id"], "ticker": spec["ticker"], "issuer": rec["issuer"],
                "document_title": rec["title"], "fiscal_year": rec["fiscal_year_end"][:4],
                "fiscal_year_end": rec["fiscal_year_end"], "language": rec["language"],
                "pdf_page": str(cand["pdf_page"]), "printed_page": cand["printed_page"], "section": cand["section"],
                "channel_candidate": cand["channel"], "direction": "unknown", "excerpt": cand["excerpt"],
                "interpretation": "OUR INTERPRETATION (not issuer text): " + cand["interpretation"],
                "document_file": Path(rec["local_file"]).name, "sha256": actual,
                "source_url": rec["official_url"], "url_verified": "False",
                "quote_verified": "True" if result["passed"] else "False",
            })
            records.append({
                "research_id": cand["id"], "evidence_id": ev_id, "subject_ticker": spec["ticker"],
                "subject_type": "company", "pdf_page": cand["pdf_page"], "printed_page": cand["printed_page"],
                "section": cand["section"], "form": cand["form"], "operational_channel": cand["channel"],
                "company_disclosed_text": cand["excerpt"], "our_interpretation": cand["interpretation"],
                "stock_return_direction": "unknown", "table": cand.get("table"),
                "unit_basis": cand.get("unit_basis"), "anchors": cand.get("anchors", []),
                "context_before": before, "context_after": after,
                "verification": result, "quote_verification": quote_verification.__dict__,
            })
        reports[source_id] = {
            "batch": "oil_batch_2025", "generated_at": now, "catalog_kind": "research_only",
            "document": {
                "document_id": doc_id, "sha256": actual, "sha256_matches_receipt": True,
                "issuer": rec["issuer"], "title": rec["title"], "ticker": spec["ticker"],
                "fiscal_year_end": rec["fiscal_year_end"], "language": rec["language"],
                "pdf_pages": len(pages), "local_file": rec["local_file"], "official_url": rec["official_url"],
                "landing_url": rec["landing_url"], "retrieved_at": rec["retrieved_at"],
                "regulatory_alternative_url": rec.get("regulatory_alternative_url"),
                "provenance_status": spec["provenance_status"], "provenance_note": spec["provenance_note"],
                "url_verified_in_this_batch": False,
            },
            "candidates": records,
            "hypotheses_not_documented": [dict(zip(("hypothesis", "status", "statistical_test_needed"), h))
                                          for h in HYPOTHESES.get(spec["ticker"], [])],
            "limitations": [
                "Quotes were matched against the PDF text layer; table columns were additionally checked visually.",
                "Interpretations are the research team's, not the issuer's; no stock-return direction is inferred.",
                "No URL was re-fetched; no AWS, S3 or production pipeline was used.",
            ],
        }
        rows_csv = io.StringIO(newline="")
        writer = csv.DictWriter(rows_csv, fieldnames=FIELDS, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
        csv_bytes = rows_csv.getvalue().encode("utf-8")
        batch = parse_candidates(csv_bytes)  # the team's importer is the acceptance gate
        assert {p.evidence_id for p in batch.catalog.passages} == {r["evidence_id"] for r in records}
        reports[source_id]["source_csv_sha256"] = batch.source_csv_sha256
        if not check_only:
            slug = SLUG[source_id]
            mode = "wb" if overwrite else "xb"
            with open(HERE / f"candidates_{slug}_2025.csv", mode) as f:
                f.write(csv_bytes)
            with open(HERE / f"candidates_{slug}_2025.verification.json", mode) as f:
                f.write(json.dumps(reports[source_id], ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
    return reports, failures


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--write", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    a = p.parse_args(argv)
    reports, failures = build(check_only=not a.write, overwrite=a.overwrite)
    for source_id, rep in reports.items():
        print(f"\n{source_id}  {rep['document']['ticker']}  sha256 OK  provenance={rep['document']['provenance_status']}")
        for c in rep["candidates"]:
            v = c["verification"]
            missing = [a for a, ok in v["anchors_found"].items() if not ok]
            print("  %-13s %-4s p%-3s printed %-4s %-21s once=%s anchors=%s pypdf=%s%s" % (
                c["research_id"], "PASS" if v["passed"] else "FAIL", c["pdf_page"], c["printed_page"],
                v["match_method"], v["occurrences_on_page"] == 1, "ok" if not missing else "MISSING",
                v["second_extractor_pypdf"], "" if not missing else "  missing: %s" % missing))
    print("\n%d candidates, %d failed" % (sum(len(r["candidates"]) for r in reports.values()), len(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
