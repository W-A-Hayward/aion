"""Validate an attached recovery manifest with the existing bounded local collector.

Never executes archive code. Preserves all 52 register entries, prior objects and
quarantines. A recovery URL/claim is not a verified source or an approved citation.
"""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit, urldefrag
import zipfile

from audit import audit
from extract import HTML, SERIES
from network import Client, now, safe_url
from pipeline import Workflow, ROOT, FRED, immutable, write_json, status_summary
from register import sha

KINDS = {'pdf', 'html', 'fred_csv', 'reference_only', 'alias', 'deferred'}


def read_bundle(path, register_ids):
    """Read one bounded JSON member, never extract or import a supplied executable."""
    if path.stat().st_size > 5_000_000:
        raise ValueError('Recovery archive exceeds limit')
    with zipfile.ZipFile(path) as z:
        members = [i for i in z.infolist() if i.filename == 'ripple_source_recovery/source_manifest.json']
        if len(members) != 1 or members[0].file_size > 1_000_000:
            raise ValueError('One bounded manifest is required')
        raw = z.read(members[0]); data = json.loads(raw)
    rows = data.get('sources')
    if not isinstance(rows, list) or not rows or len(rows) > 100:
        raise ValueError('Missing or excessive recovery candidates')
    seen = set()
    for r in rows:
        identifier = r.get('id', '')
        if not re.fullmatch(r'SRC-\d{3}(?:-Q[1-4])?', identifier) or identifier in seen:
            raise ValueError('Invalid or duplicate recovery ID')
        seen.add(identifier)
        parent = r.get('parent', identifier)
        if parent not in register_ids or r.get('kind') not in KINDS:
            raise ValueError('Unmatched register parent or unsupported source kind')
        if parent != identifier and not identifier.startswith(parent + '-'):
            raise ValueError('Child publication does not match parent')
        safe_url(r['url'])
        if r.get('publisher_page'): safe_url(r['publisher_page'])
        if not isinstance(r.get('name'), str) or not isinstance(r.get('period'), str):
            raise ValueError('Name and period claims required')
    for r in rows:
        if r['kind'] == 'alias' and (r.get('alias_of') not in seen or r['alias_of'] == r['id']):
            raise ValueError('Unresolved alias')
    return data, raw, sha(path.read_bytes())


def validate_extraction(row, extracted, artifact):
    expected = {'pdf': 'pdf', 'html': 'html', 'fred_csv': 'time_series'}[row['kind']]
    check = {'format': 'UNVERIFIED', 'issuer_title_period': 'UNVERIFIED',
             'financial_claims': 'UNVERIFIED', 'citation_approved': False}
    if not extracted or extracted.get('kind') != expected:
        check['format'] = 'failed_expected_' + expected
        return check, False
    check['format'] = 'validated'
    if row['kind'] == 'fred_csv':
        sid = FRED[row.get('parent', row['id'])]
        records = extracted['records']; dates = [v['date'] for v in records]
        if not dates or len(dates) != len(set(dates)) or dates != sorted(dates):
            raise ValueError('Empty, duplicated or unordered series dates')
        if extracted.get('source_columns', [None, None])[1] != sid:
            raise ValueError('CSV series does not match requested ID')
        if any(v['series_id'] != sid or v['unit'] != SERIES[sid][0] for v in records):
            raise ValueError('Series identity or units mismatch')
        if any(d < '2021-11-12' or d > '2026-11-15' for d in dates):
            raise ValueError('Series date outside requested recovery window')
        # The existing parser rejects nonfinite/nonnumeric values and preserves nulls.
        if not any(v['value'] is not None for v in records):
            raise ValueError('Series contains no numeric observations')
        check.update(series_id=sid, units=SERIES[sid][0], observations=len(records),
                     first=dates[0], last=dates[-1], missing_values=extracted['missing_count'],
                     structure='validated_series_dates_units_numeric_values',
                     coverage='window_edges_present' if dates[0] <= '2021-11-19' and dates[-1] >= '2026-11-08' else 'partial_window_requires_review')
        return check, check['coverage'] == 'window_edges_present'
    pages = extracted.get('pages', [{'pdf_page': None, 'text': extracted.get('text', '')}])
    check['observed_title_excerpt'] = pages[0]['text'][:500] if pages else ''
    check['publication_date_candidates'] = extracted.get('publication_date_candidates', [])
    check['issuer_text_check'] = artifact.get('issuer_text_check', {'status': 'UNVERIFIED'})
    check['period_check'] = artifact.get('period_check', 'UNVERIFIED')
    check['issuer_title_period'] = 'manual_review_required'
    # Format/automated term matches do not qualify new documents for evidence use.
    return check, False


def publisher_link(client, row, artifact, storage):
    url = row.get('publisher_page')
    result = {'status': 'UNVERIFIED', 'publisher_page': url, 'scope': 'link_only_not_content_identity'}
    if not url: return result
    if url == row['url']:
        result['status'] = 'same_URL_no_independent_link_proof'
        return result
    host = urlsplit(url).hostname
    receipt = client.get(url, {host, host.removeprefix('www.'), 'www.' + host.removeprefix('www.')})
    result['retrieval_status'] = receipt['status']
    result['reason'] = receipt.get('reason')
    body = receipt.get('body')
    if not body: return result
    digest = sha(body); immutable(storage / 'objects' / digest, body)
    result['page_sha256'] = digest; result['retrieved_at'] = receipt.get('retrieved_at')
    parsed = HTML(); parsed.feed(body.decode('utf-8', errors='replace'))
    targets = {row['url'], artifact.get('final_url')}
    hrefs = {urldefrag(urljoin(receipt.get('url', url), link['href']))[0] for link in parsed.links}
    result['status'] = 'exact_href_observed' if targets & hrefs else 'exact_href_not_found'
    return result


def integrate(workflow, base, rows):
    result = deepcopy(base); entries = {s['source_id']: s for s in result['sources']}
    records = []
    for row in rows:
        entry = entries[row.get('parent', row['id'])]
        rec = {'id': row['id'], 'name_claim': row['name'], 'period_claim': row['period'],
               'kind': row['kind'], 'url': row['url'], 'publisher_page': row.get('publisher_page'),
               'supplied_note_UNVERIFIED': row.get('note'), 'checked_at': now(), 'sha256': None,
               'source_verification': 'UNVERIFIED', 'citation_approved': False}
        kind = row['kind']
        if kind in {'alias', 'deferred', 'reference_only'}:
            rec.update(status={'alias': 'related_reference_no_duplicate_download', 'deferred': 'deferred_backend_work',
                               'reference_only': 'reference_only_not_fetched'}[kind], related_source=row.get('alias_of'))
        else:
            reg = dict(entry['register'], Title=row['name'], Period=row['period'])
            host = urlsplit(row['url']).hostname
            allowed = {host, host.removeprefix('www.'), 'www.' + host.removeprefix('www.')}
            a, ext = workflow.acquire(row['url'], reg, allowed, role='recovery_candidate')
            a = deepcopy(a); a['recovery_candidate_id'] = row['id']
            a['requested_period'] = row['period']; a['requested_title'] = row['name']
            rec.update(status=a['retrieval_status'], sha256=a.get('sha256'), final_url=a.get('final_url'),
                       reason=a.get('http_receipt', {}).get('reason'), http_status=a.get('http_receipt', {}).get('http_status'),
                       retrieved_at=a.get('retrieved_at'))
            if a.get('sha256'):
                try:
                    check, qualifies = validate_extraction(row, ext, a)
                except (ValueError, KeyError, IndexError) as error:
                    check, qualifies = {'format': 'validation_failed', 'error': str(error), 'financial_claims': 'UNVERIFIED'}, False
                rec['validation'] = check
                proof = publisher_link(workflow.client, row, a, workflow.storage)
                rec['publisher_link_check'] = proof
                a['recovery_validation'] = check; a['publisher_link_check'] = proof
                a['quarantine'] = bool(a.get('quarantine')) or not qualifies
                a['source_verification'] = 'publisher_page_exact_href_observed' if proof['status'] == 'exact_href_observed' else a.get('source_verification', 'UNVERIFIED')
                rec['source_verification'] = a['source_verification']
                rec['status'] = 'structured_validated_local' if qualifies and not a['quarantine'] else 'acquired_manual_review_required'
                if a['quarantine']: a['attention'] = 'Recovery acquisition: document identity/period or structured validation needs review; no automatic evidence approval.'
                # Preserve existing observations and quarantine even if this new receipt differs.
                if not any(old.get('sha256') == a['sha256'] and old.get('original_url') == a.get('original_url') for old in entry['artifacts']):
                    entry['artifacts'].append(a)
                if qualifies and not a['quarantine']:
                    entry['usability'] = 'usable'
                    entry['attention'] = [t for t in entry['attention'] if not t.startswith('No qualified')]
            else:
                entry['artifacts'].append(a)
            if not a.get('sha256') and row['id'] == 'SRC-026':
                rec['existing_CDN_PDF_quarantine'] = 'unchanged; SEC HTML would be a separate document'
        previous = next((r for r in entry.get('recovery_candidates', []) if r['id'] == rec['id']), None)
        if previous:
            rec['previous_checks'] = previous.get('previous_checks', []) + [{k: v for k, v in previous.items() if k != 'previous_checks'}]
        entry['recovery_candidates'] = [r for r in entry.get('recovery_candidates', []) if r['id'] != rec['id']] + [rec]
        records.append(rec)
        write_json(workflow.run / 'recovery_receipts' / (row['id'] + '.json'), rec)
        print(row['id'] + ': ' + rec['status'], flush=True)
    result.update(run_id=workflow.run.name, completed_at=now(), previous_run_id=base['run_id'],
                  aws='NOT_CONTACTED', financial_citations_automatically_verified=False)
    all_records = [r for e in result['sources'] for r in e.get('recovery_candidates', [])]
    result['recovery_summary'] = {'candidates': len(all_records), 'register_entries_covered': sum(bool(e.get('recovery_candidates')) for e in result['sources']),
                                  'checked_this_run': len(records), 'counts': dict(Counter(r['status'] for r in all_records)), 'automatic_citation_approvals': 0}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--base-inventory', type=Path, required=True)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--ids', help='Only recheck these candidate IDs; retain all other prior results')
    args = parser.parse_args()
    base = json.loads(args.base_inventory.read_text())
    if len(base.get('sources', [])) != 52: raise ValueError('Complete base catalog required')
    # Recheck the base corpus before any network activity or new run.
    for entry in base['sources']:
        for a in entry['artifacts']:
            if a.get('sha256') and sha((args.base_inventory.parents[2] / a['blob']).read_bytes()) != a['sha256']:
                raise ValueError('Base object hash mismatch')
    data, raw, archive_hash = read_bundle(args.bundle, {s['source_id'] for s in base['sources']})
    storage = args.base_inventory.parents[2]
    immutable(storage / 'recovery_manifests' / archive_hash / 'source_manifest.json', raw)
    workflow = Workflow(storage, client=Client(offline=args.offline))
    rows = data['sources']
    if args.ids:
        selected = set(args.ids.split(','))
        if not selected <= {r['id'] for r in rows}: raise ValueError('Unknown candidate ID')
        rows = [r for r in rows if r['id'] in selected]
    result = integrate(workflow, base, rows)
    result['recovery_manifest'] = {'archive_sha256': archive_hash, 'manifest_sha256': sha(raw), 'supplied_claims': 'UNVERIFIED'}
    staged = workflow.stage(result['sources'])
    summary = status_summary(result['sources'])
    summary.update(unique_content_objects=len({a['sha256'] for e in result['sources'] for a in e['artifacts'] if a.get('sha256')}),
                   kb_text_files=staged['knowledge_base_text_files'], structured_preparation_files=len(staged['structured_files']))
    result['summary'] = summary
    for entry in result['sources']:
        write_json(workflow.run / 'receipts' / (entry['source_id'] + '.json'), entry)
    write_json(workflow.run / 'inventory.json', result)
    robots = {}
    for origin, (receipt, _) in workflow.client.robots.items():
        robots[origin] = {k: v for k, v in receipt.items() if k != 'body'}
        if receipt.get('body'):
            digest, blob = workflow.store(receipt['body']); robots[origin].update(sha256=digest, blob=blob)
    write_json(workflow.run / 'robots_receipts.json', robots)
    workflow.report(result); audit(workflow.run)
    write_json(workflow.run / 'recovery_summary.json', result['recovery_summary'])
    print(json.dumps({'run': str(workflow.run), 'recovery': result['recovery_summary'], 'summary': summary}, indent=2))


if __name__ == '__main__': main()
