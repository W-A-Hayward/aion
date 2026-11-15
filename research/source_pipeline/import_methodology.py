"""Offline import of the inspected, user-supplied S&P methodology PDF.

This is a hash-bound local review, not verification of the download URL or an
approval to apply later index-rule changes to an earlier holdings snapshot.
"""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

from audit import audit
from extract import extract
from network import Client, now
from pipeline import Workflow, write_json, status_summary
from register import sha

REVIEWED_HASH = '4113c09c0d9d24f1b396a1d4558b0b5d238fb14b9df454f3bd3cfd762fd2c150'


def inspect_document(raw, extraction):
    if sha(raw) != REVIEWED_HASH: raise ValueError('Different PDF bytes require a new identity and edition review')
    if extraction.get('kind') != 'pdf' or extraction.get('page_count') != 42:
        raise ValueError('Reviewed PDF format or page count differs')
    anchors = []
    for field, page, printed, text in [
        ('title', 1, None, 'S&P/TSX Canadian Indices\nMethodology'),
        ('edition', 1, None, 'November 2026'),
        ('issuer_label', 1, None, 'S&P Dow Jones Indices: Index Methodology'),
        ('tsx60_section', 16, '15', 'S&P/TSX 60 Methodology'),
        ('future_rule_date', 32, '31', '18-Dec-26'),
    ]:
        original = next(p['text'] for p in extraction['pages'] if p['pdf_page'] == page)
        if text not in original: raise ValueError('Reviewed text anchor missing: ' + field)
        start = original.index(text)
        anchors.append(dict(field=field, pdf_page=page, printed_page=printed, start=start, end=start+len(text), text=text))
    return {
        'document_sha256': REVIEWED_HASH, 'reviewed_at': now(), 'reviewed_by': 'Codex assistant',
        'method': 'Read of supplied PDF text; title, issuer label, cover edition, Appendix A and change log',
        'edition': {'label': 'November 2026', 'year_month': '2026-11', 'precision': 'month', 'pdf_page': 1},
        'publication_date': None, 'download_date': None, 'source_url_verification': 'UNVERIFIED',
        'financial_claims': 'UNVERIFIED', 'citation_approved': False, 'stock_return_direction': 'unknown',
        'anchors': anchors,
        'reading_map': [
            {'section': 'Index objective and index families', 'pdf_page': 4, 'printed_page': '3'},
            {'section': 'GICS sector classification', 'pdf_page': 8, 'printed_page': '7'},
            {'section': 'Index maintenance: check the index-specific scope', 'pdf_page': 9, 'printed_page': '8'},
            {'section': 'Appendix A — S&P/TSX 60 methodology', 'pdf_page': 16, 'printed_page': '15'},
            {'section': 'Appendix I — methodology changes', 'pdf_page': 32, 'printed_page': '31'},
        ],
        'temporal_limit': 'The November 2026 edition includes changes effective after close on 2026-12-18 (PDF p.32 / printed p.31). Do not apply those future rules to XIU holdings dated 2026-11-12. Edition month is not an exact publication day or the effective date of every rule.',
        'scope_limit': 'Index methodology context only. It does not supply XIU fund holdings, current sector weights, oil sensitivities or stock-return direction. Appendix A describes S&P/TSX 60 constituent changes as needed; do not substitute a blanket quarterly constituent-reconstitution rule.',
    }


def merge_supplied(base, artifact, review):
    result = deepcopy(base)
    if len(result.get('sources', [])) != 52: raise ValueError('Complete 52-source base required')
    entry = next(e for e in result['sources'] if e['source_id'] == 'SRC-006')
    if not any(a.get('sha256') == artifact['sha256'] for a in entry['artifacts']): entry['artifacts'].append(artifact)
    note = 'Supplied PDF edition November 2026 reviewed locally. Download URL remains UNVERIFIED; future December 2026 rule changes must not be applied to November holdings.'
    if note not in entry['attention']: entry['attention'].append(note)
    # Provenance is still unresolved; do not silently clear the original needs-attention state.
    for rec in entry.get('recovery_candidates', []):
        if rec['id'] != 'SRC-006': continue
        if rec.get('sha256') != artifact['sha256']:
            rec['previous_checks'] = rec.get('previous_checks', []) + [{k:v for k,v in rec.items() if k != 'previous_checks'}]
        rec.update(status='supplied_identity_reviewed_provenance_pending', sha256=artifact['sha256'],
                   checked_at=review['reviewed_at'], reason='Local file supplied; no verified acquisition receipt or online byte comparison',
                   source_verification='UNVERIFIED_user_supplied_file', identity_review=review,
                   validation={'format': 'validated_pdf', 'page_count':42, 'edition':review['edition'],
                               'source_url':'UNVERIFIED', 'publication_day':'UNVERIFIED', 'citation_approved':False})
    records = [r for e in result['sources'] for r in e.get('recovery_candidates', [])]
    result['recovery_summary']['counts'] = dict(Counter(r['status'] for r in records))
    result['recovery_summary']['supplied_identity_reviews_applied'] = 1
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', type=Path, required=True)
    parser.add_argument('--base-inventory', type=Path, required=True)
    args = parser.parse_args()
    raw = args.pdf.read_bytes()
    if sha(raw) != REVIEWED_HASH: raise ValueError('Unreviewed source hash')
    extracted = extract(args.pdf); review = inspect_document(raw, extracted)
    base = json.loads(args.base_inventory.read_text()); storage = args.base_inventory.parents[2]
    workflow = Workflow(storage, Client(offline=True)); digest, blob = workflow.store(raw)
    entry = next(e for e in base['sources'] if e['source_id'] == 'SRC-006')
    a = dict(sha256=digest, blob=blob, bytes=len(raw), original_filename=args.pdf.name,
             original_url=None, final_url=None, retrieved_at=None, checked_at=review['reviewed_at'],
             retrieval_status='provided_local_file', role='supplied_methodology', publisher='S&P Dow Jones Indices',
             title='S&P/TSX Canadian Indices Methodology', source_verification='UNVERIFIED_user_supplied_file',
             content_verification='local_title_issuer_label_and_edition_reviewed', quarantine=True)
    a, ext = workflow.enrich(a, entry['register'])
    if not ext: raise ValueError('Supplied PDF extraction failed')
    a.update(edition=review['edition'], reporting_period=None, publication_date=None,
             period_check='cover_edition_2026-11_not_exact_publication_or_effective_date',
             supplied_identity_review=review, current_link_status='UNVERIFIED_no_acquisition_receipt',
             attention='Supplied PDF identity/edition reviewed. Official provenance remains pending. ' + review['temporal_limit'],
             content_verification_scope='Title, issuer label, edition and selected section headings only; no financial citation approval.')
    result = merge_supplied(base, a, review)
    result.update(run_id=workflow.run.name, previous_run_id=base['run_id'], completed_at=now())
    staged = workflow.stage(result['sources']); summary = status_summary(result['sources'])
    summary.update(unique_content_objects=len({a['sha256'] for e in result['sources'] for a in e['artifacts'] if a.get('sha256')}),
                   kb_text_files=staged['knowledge_base_text_files'], structured_preparation_files=len(staged['structured_files']))
    result['summary'] = summary
    for e in result['sources']: write_json(workflow.run/'receipts'/(e['source_id']+'.json'), e)
    write_json(workflow.run/'supplied_methodology_review.json', review)
    write_json(workflow.run/'inventory.json', result); workflow.report(result); audit(workflow.run)
    print(json.dumps({'run':str(workflow.run), 'summary':summary, 'review':str(workflow.run/'supplied_methodology_review.json')}))


if __name__ == '__main__': main()
