"""Apply an explicit local document-identity review in a new immutable inventory.

No network. Does not approve financial excerpts, change an existing evidence
catalog, or clear quarantines outside this recovery batch.
"""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

from audit import audit
from network import Client, now
from pipeline import Workflow, write_json, status_summary
from register import sha


def reviewed_inventory(base, reviews, storage):
    result = deepcopy(base)
    if not reviews: raise ValueError('Empty review batch')
    for review in reviews:
        if review.get('scope') != 'document_identity_only' or review.get('citation_approved') is not False:
            raise ValueError('Only identity review is supported')
        if review.get('financial_claims') != 'UNVERIFIED' or review.get('stock_return_direction') != 'unknown':
            raise ValueError('Cannot approve claims or infer stock-return direction')
        entry = next(e for e in result['sources'] if e['source_id'] == review['register_id'])
        matches = [a for a in entry['artifacts'] if a.get('sha256') == review['document_sha256']
                   and a.get('recovery_candidate_id') == review['candidate_id'] and a.get('role') == 'recovery_candidate']
        if len(matches) != 1: raise ValueError('Review must identify exactly one recovery artifact')
        a = matches[0]
        if sha((storage / a['blob']).read_bytes()) != review['document_sha256']:
            raise ValueError('Reviewed source hash mismatch')
        if a.get('actual_format') not in {'html', 'pdf'}: raise ValueError('Only documents can receive an identity review')
        extracted = json.loads((storage / a['extraction_file']).read_text())
        if extracted['kind'] == 'html' and extracted.get('title') != review['document_title']: raise ValueError('Document title mismatch')
        if {anchor['field'] for anchor in review['anchors']} != {'title', 'publication_date', 'reporting_period'}:
            raise ValueError('Identity/date/period anchors required')
        for anchor in review['anchors']:
            text = extracted['text'] if extracted['kind'] == 'html' else next(p['text'] for p in extracted['pages'] if p['pdf_page'] == anchor.get('pdf_page'))
            if not anchor['text'] or text[anchor['start']:anchor['end']] != anchor['text']:
                raise ValueError('Review anchor does not match exact extraction offsets')
        a.update(title=review['document_title'], publication_date=review['publication_date'],
                 reporting_period=review['reporting_period'], source_verification=review['source_verification'],
                 content_verification='document_identity_reviewed_locally_financial_claims_UNVERIFIED',
                 content_verification_scope='Issuer, title, publication date and reporting period only. No financial quotation approval.',
                 recovery_identity_review=review, quarantine=False,
                 attention='Identity reviewed. Financial passages and table interpretation still require review.')
        for rec in entry['recovery_candidates']:
            if rec['id'] == review['candidate_id']:
                rec['status'] = 'identity_reviewed_local'; rec['identity_review'] = review
                rec['validation']['issuer_title_period'] = 'reviewed_against_local_source_text'
                rec['source_verification'] = review['source_verification']
        # A quarterly release does not fulfil a register request for an annual report.
        if entry['usability'] == 'needs_attention': entry['usability'] = 'context_only'
        entry['attention'] = [t for t in entry['attention'] if not t.startswith('No qualified')]
        note = review['remaining_scope']
        if note not in entry['attention']: entry['attention'].append(note)
    records = [r for e in result['sources'] for r in e.get('recovery_candidates', [])]
    result['recovery_summary']['counts'] = dict(Counter(r['status'] for r in records))
    result['recovery_summary']['identity_reviews_applied'] = len(reviews)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-inventory', type=Path, required=True)
    parser.add_argument('--reviews', type=Path, required=True)
    args = parser.parse_args(); base = json.loads(args.base_inventory.read_text())
    storage = args.base_inventory.parents[2]; reviews = json.loads(args.reviews.read_text())['reviews']
    result = reviewed_inventory(base, reviews, storage)
    workflow = Workflow(storage, Client(offline=True))
    result.update(run_id=workflow.run.name, previous_run_id=base['run_id'], completed_at=now())
    staged = workflow.stage(result['sources']); summary = status_summary(result['sources'])
    summary.update(unique_content_objects=len({a['sha256'] for e in result['sources'] for a in e['artifacts'] if a.get('sha256')}),
                   kb_text_files=staged['knowledge_base_text_files'], structured_preparation_files=len(staged['structured_files']))
    result['summary'] = summary
    for entry in result['sources']:
        write_json(workflow.run / 'receipts' / (entry['source_id'] + '.json'), entry)
    write_json(workflow.run / 'identity_reviews.json', {'reviews': reviews})
    write_json(workflow.run / 'inventory.json', result)
    workflow.report(result); audit(workflow.run)
    print(json.dumps({'run': str(workflow.run), 'summary': summary, 'recovery': result['recovery_summary']}, indent=2))


if __name__ == '__main__': main()
