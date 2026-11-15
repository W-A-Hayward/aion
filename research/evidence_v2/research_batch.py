"""Offline research batch: exact PDF passages, full page context, v2 projection.

Only --build creates new files in the isolated batch directory. No network or
production imports. Existing documents, catalogs and source receipts are read-only.
"""
import argparse
import csv
from dataclasses import replace
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import subprocess

from import_candidates import FIELDS, parse_candidates
from schema import Catalog, ValidationError, Verification, digest, require

ROOT = Path(__file__).resolve().parent
BATCH = ROOT / "batch_2025_rbc_cnq_cpkc"
SOURCES = ROOT.parent / "source_documents"
MANIFEST = SOURCES / "runs/20261115T131702Z_d4fbb4fa/manifest.json"
EXTRA = ("evidence_kind", "stock_return_direction", "disclosed_fact", "limitations",
         "source_context_before", "source_context_after", "quote_start", "quote_end",
         "source_page_sha256", "table_context", "source_provenance_status", "visual_review_status")


def read_pdf(entry):
    path = SOURCES / entry["local_file"]
    raw = path.read_bytes()
    require(digest(raw) == entry["sha256"] and raw.startswith(b"%PDF-"), "PDF identity/hash mismatch")
    result = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript",
                             str(SOURCES / "pdf_metadata.js"), str(path)],
                            capture_output=True, text=True, check=True, timeout=60)
    return {p["pdf_page"]: p["text"] for p in json.loads(result.stdout)["pages"]}


def quote_span(page, start, end=None, occurrence=0):
    positions, offset = [], 0
    while (i := page.find(start, offset)) >= 0:
        positions.append(i)
        offset = i + len(start)
    require(len(positions) > occurrence >= 0, "Selected quote start absent")
    first = positions[occurrence]
    last = first + len(start) if end is None else page.find(end, first) + len(end)
    require(last >= first + len(start), "Selected quote end absent")
    return first, last, page[first:last]


def validate_row(row, page, expected_sha):
    require(row["sha256"] == expected_sha, "Candidate/document hash mismatch")
    require(row["direction"] == row["stock_return_direction"] == "unknown", "Unknown direction required")
    require(row["evidence_kind"] == "operational", "Statistics must remain separate")
    begin, end = int(row["quote_start"]), int(row["quote_end"])
    require(0 <= begin < end <= len(page) and page[begin:end] == row["excerpt"], "Exact quote/page mismatch")
    require(row["source_context_before"] == page[:begin] and row["source_context_after"] == page[end:],
            "Surrounding source context mismatch")
    require(digest(page.encode()) == row["source_page_sha256"], "Source page text mismatch")
    table = json.loads(row["table_context"])
    if table:
        require(all(table.get(k) for k in ("title", "units", "columns", "scope", "footnote_review")),
                "Financial table needs heading, units, column scope and footnotes")
    if row["ticker"] == "CP.TO":
        require(row["url_verified"] == "False" and row["source_provenance_status"] == "pending_issuer_to_cdn",
                "CPKC official-source provenance must remain pending")


def csv_bytes(rows):
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=FIELDS + EXTRA)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def project_v2(raw, checked_at, source_entry, source_pages):
    """Explicit lossless base-field projection; supplemental research fields stay in CSV."""
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"), newline="")))
    require(bool(rows) and set(rows[0]) == set(FIELDS + EXTRA), "Unexpected extended candidate CSV")
    for row in rows:
        require(row["ticker"] == source_entry["ticker"], "Candidate ticker/source mismatch")
        validate_row(row, source_pages[int(row["pdf_page"])], source_entry["sha256"])
    buf = io.StringIO(newline="")
    out = csv.DictWriter(buf, fieldnames=FIELDS)
    out.writeheader()
    out.writerows({k: r[k] for k in FIELDS} for r in rows)
    imported = parse_candidates(buf.getvalue().encode()).catalog
    artifact_hash = digest(raw)
    quote = Verification("verified", "exact_PDFKit_page_substring_with_context_review",
                         artifact_hash, checked_at, "Codex local research review")
    docs = []
    for d in imported.documents:
        source = Verification("unverified", "issuer_to_cdn_link_pending", artifact_hash) if rows[0]["ticker"] == "CP.TO" else Verification(
            "reported_verified", "official_issuer_URL_in_existing_acquisition_receipt", artifact_hash)
        docs.append(replace(d, source_verification=source,
            issuer_verification=Verification("reported_verified", "local_report_identity_review", artifact_hash),
            hash_verification=Verification("verified", "local_source_PDF_sha256", d.sha256,
                                          checked_at, "Codex local research review")))
    catalog = Catalog(tuple(docs), tuple(replace(p, quote_verification=quote) for p in imported.passages))
    catalog.validate()
    return catalog


def build():
    specs = json.loads((BATCH / "selection.json").read_text())
    manifest = json.loads(MANIFEST.read_text())
    entries = {e["id"]: e for e in manifest["entries"]}
    stamp = datetime.now(timezone.utc).isoformat()
    outputs, ledger = {}, {"reviewed_at": stamp, "mode": "local_research_not_published", "documents": []}
    for company in specs:
        entry = entries[company["source_id"]]
        pages = read_pdf(entry)
        rows = []
        for candidate in company["candidates"]:
            page = pages[candidate["page"]]
            start, end, quote = quote_span(page, candidate["start"], candidate.get("end"), candidate.get("occurrence", 0))
            row = dict(zip(FIELDS, [candidate["id"], entry["ticker"], entry["issuer"], entry["title"],
                "2025", entry["fiscal_year_end"], "en", candidate["page"], candidate["printed"],
                candidate["section"], candidate["channel"], "unknown", quote, candidate["interpretation"],
                Path(entry["local_file"]).name, entry["sha256"], entry["official_url"],
                "False" if entry["ticker"] == "CP.TO" else "True", "True"]))
            row.update(evidence_kind="operational", stock_return_direction="unknown",
                disclosed_fact=candidate["fact"], limitations=candidate["limitations"],
                source_context_before=page[:start], source_context_after=page[end:], quote_start=start, quote_end=end,
                source_page_sha256=digest(page.encode()), table_context=json.dumps(candidate.get("table", {}), ensure_ascii=False),
                source_provenance_status="pending_issuer_to_cdn" if entry["ticker"] == "CP.TO" else "official_issuer_url_in_acquisition_receipt",
                visual_review_status="rendered_page_reviewed" if candidate["page"] in company["visual_pages"] else "original_PDF_text_reviewed")
            validate_row(row, page, entry["sha256"])
            rows.append(row)
        require(5 <= len(rows) <= 8, "Expected five to eight supported candidates per company")
        raw = csv_bytes(rows)
        catalog = project_v2(raw, stamp, entry, pages)
        outputs[company["slug"] + "_candidates.csv"] = raw
        outputs[company["slug"] + "_catalog.json"] = catalog.to_bytes()
        report = [f"# {entry['issuer']} — recherche documentaire 2025", "", company["summary"], "",
            f"Source : **{entry['title']}**, exercice clos le {entry['fiscal_year_end']}. Publication : non vérifiée.",
            f"[URL d'origine]({entry['official_url']}) ; [URL finale]({entry['http_receipt']['final_url']}).",
            f"SHA-256 du PDF : `{entry['sha256']}`.", f"Fichier local : `{(SOURCES / entry['local_file']).resolve()}`.", "",
            "Provenance : **EN ATTENTE — lien émetteur→CDN non établi**." if entry["ticker"] == "CP.TO" else
            "Provenance : URL du domaine de l'émetteur conservée dans le reçu d'acquisition ; aucun contrôle réseau nouveau.", "",
            "Les citations sont des sous-chaînes exactes du texte PDFKit des pages d'origine, avec sauts de ligne conservés. Les tableaux sélectionnés ont aussi été inspectés dans le rendu du PDF. Le contexte complet avant/après est conservé dans chaque ligne CSV ; il ne doit pas être confondu avec l'interprétation.", "",
            "## Candidats", ""]
        for row in rows:
            table = json.loads(row["table_context"])
            report += [f"### {row['evidence_id']} — {row['channel_candidate']}", "",
                f"PDF **{row['pdf_page']}**, page imprimée **{row['printed_page']}** — {row['section']}", "",
                "**Citation originale :**", "", *["> " + line for line in row["excerpt"].splitlines()], "",
                "**Fait divulgué :** " + row["disclosed_fact"], "",
                "**Notre interprétation :** " + row["interpretation"], "",
                "**Limites :** " + row["limitations"], ""]
            if table:
                report += ["**Contexte de tableau contrôlé :**", "", *[f"- {k} : {v}" for k,v in table.items()], ""]
        report += ["## Validation statistique encore nécessaire", "", company["statistics"], "",
            "Tous les passages restent `evidence_kind=operational` et `stock_return_direction=unknown`. Aucune contribution au beta de XIU, causalité boursière ou relation fournisseur-client nommée n'est créée. Aucun contexte XIU n'est ajouté à ce lot.", "",
            "## Périmètre de vérification", "", f"Revue locale : {stamp}. Citations et hash vérifiés ; interprétations non validées statistiquement. Les champs v2 sont exportés dans le catalogue de recherche associé. La lecture directe de ce CSV étendu par l'ancien importateur n'est pas autorisée : la projection explicite de `research_batch.py` conserve les champs additionnels dans le CSV.", ""]
        outputs[company["slug"] + "_research.md"] = "\n".join(report).encode()
        ledger["documents"].append({"ticker": entry["ticker"], "sha256": entry["sha256"], "candidates": len(rows),
            "csv_sha256": digest(raw), "printed_page_mapping": {str(c["page"]):c["printed"] for c in company["candidates"]},
            "visually_reviewed_pdf_pages": company["visual_pages"], "source_provenance_status": rows[0]["source_provenance_status"]})
    outputs["validation_receipt.json"] = json.dumps(ledger, ensure_ascii=False, indent=2).encode()
    require(not any((BATCH / name).exists() for name in outputs), "Refusing to overwrite an existing research artifact")
    for name, data in outputs.items():
        with (BATCH / name).open("xb") as stream:
            stream.write(data)
    print(json.dumps(ledger, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", required=True)
    parser.parse_args()
    build()
