"""Publish a local browser bundle from audited acquisition files. No network or AWS.

Original PDFs are not copied. Immutable bundles retain every available extraction;
the small browser catalog is replaced atomically only with --activate.
"""
import argparse
import json
from pathlib import Path
import os
from urllib.parse import urlsplit, unquote

from register import sha
from pipeline import immutable

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT.parents[1] / 'frontend'


def encoded(obj):
    return (json.dumps(obj, ensure_ascii=False, separators=(',', ':')) + '\n').encode()


def within(root, rel):
    p = (root / rel).resolve()
    if not p.is_relative_to(root.resolve()): raise ValueError('Artifact path escapes storage')
    return p


def build(inventory_path, target=FRONTEND):
    storage = inventory_path.parents[2]
    raw = inventory_path.read_bytes(); data = json.loads(raw); version = sha(raw)
    audit = json.loads((inventory_path.parent / 'offline_audit.json').read_text())
    if len(data['sources']) != 52 or audit['source_entries'] != 52 or audit['run_id'] != data['run_id']:
        raise ValueError('A complete, audited 52-source inventory is required')
    sources = []; artifacts = {}
    for source in data['sources']:
        r = source['register']
        s = {'id': source['source_id'], 'group': r['Group'], 'priority': r['Priority'], 'publisher': r['Publisher'],
             'title': r['Title'], 'requested_period': r['Period'], 'subjects': r['Tickers'],
             'purpose': r['What to extract / purpose'], 'url': r['Official URL'], 'usability': source['usability'],
             'attention': source['attention'], 'duplicate_of': source.get('duplicate_register_url_of'),
             'artifacts': [], 'attempts': [], 'recovery_candidates': source.get('recovery_candidates', [])}
        for a in source['artifacts']:
            s['attempts'].append({'status': a['retrieval_status'], 'url': a.get('original_url'),
                                  'reason': a.get('http_receipt', {}).get('reason'), 'error': a.get('extraction_error'),
                                  'sha256': a.get('sha256')})
            h = a.get('sha256')
            if not h: continue
            if h not in s['artifacts']: s['artifacts'].append(h)
            blob = within(storage, a['blob'])
            if sha(blob.read_bytes()) != h: raise ValueError('Original source hash mismatch')
            if h in artifacts:
                existing = artifacts[h]
                if s['id'] not in existing['source_ids']: existing['source_ids'].append(s['id'])
                existing['quarantine'] |= bool(a.get('quarantine'))
                continue
            x = json.loads(within(storage, a['extraction_file']).read_text()) if a.get('extraction_status') == 'extracted' else None
            record = {k: a.get(k) for k in ['sha256', 'publisher', 'original_url', 'final_url', 'retrieved_at',
                       'publication_date', 'publication_date_candidates', 'source_verification', 'content_verification',
                       'period_check', 'extraction_status', 'extraction_error', 'date_range', 'units', 'page_count',
                       'reporting_period', 'fiscal_year_end', 'issuer_text_check', 'checked_at', 'current_link_status',
                       'content_verification_scope', 'structure_verification', 'prior_review', 'original_retrieval_status',
                       'recovery_validation', 'publisher_link_check', 'recovery_candidate_id', 'recovery_identity_review',
                       'edition', 'supplied_identity_review']}
            record.update(source_ids=[s['id']], quarantine=bool(a.get('quarantine')), format=a.get('actual_format', 'unavailable'),
                          title=a.get('title') or (x.get('title') if x else None) or r['Title'],
                          title_excerpt=a.get('observed_title_excerpt'),
                          file_label=a.get('original_filename') or unquote(urlsplit(a.get('final_url') or a.get('original_url') or '').path.split('/')[-1]) or 'Supplied snapshot',
                          attention=a.get('attention') or a.get('purpose_attention'), payload=None,
                          citation_approved=False, source_byte_check='verified_locally_during_bundle_build')
            if x is not None:
                payload = {'schema_version': 1, 'artifact_sha256': h, 'format': x['kind'], 'data': x}
                body = encoded(payload)
                path = f'research-data/{version}/{h}.json'
                immutable(target / path, body)
                record['payload'] = {'path': path, 'sha256': sha(body), 'bytes': len(body)}
                record['row_count'] = x.get('row_count')
                if x['kind'] == 'zip_csv':
                    record['datasets'] = [{k: m['data'].get(k) for k in ['kind', 'row_count', 'date_min', 'date_max', 'units']} for m in x['members']]
            artifacts[h] = record
        sources.append(s)
    if len(artifacts) != audit['verified_content_hashes']: raise ValueError('Inventory object count differs from audit')
    catalog = {'schema_version': 1, 'mode': 'local_acquired_research', 'inventory_sha256': version,
               'run_id': data['run_id'], 'catalog_as_of': data['completed_at'], 'sources': sources,
               'artifacts': list(artifacts.values()), 'summary': data['summary'],
               'recovery_summary': data.get('recovery_summary'), 'recovery_manifest': data.get('recovery_manifest'),
               'limits': ['Research usability is not citation verification.', 'Quarantined sources are excluded from default document search.',
                          'No AWS connection or new beta calculations.', 'Historical holdings are never silently replaced.']}
    body = encoded(catalog)
    if b'/Users/' in body or b'"local_file":' in body: raise ValueError('Private workstation metadata leaked')
    # Metadata-only exporter improvements get a new immutable catalog without
    # replacing an earlier catalog or duplicating unchanged extraction payloads.
    immutable(target / f'research-data/{version}/catalog-{sha(body)}.json', body)
    return catalog, body


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--inventory', type=Path); p.add_argument('--activate', action='store_true')
    args = p.parse_args()
    source = args.inventory or sorted((ROOT / 'artifacts/runs').glob('*/inventory.json'))[-1]
    catalog, body = build(source)
    if args.activate:
        temp = FRONTEND / '.library-catalog.pending.json'
        with temp.open('xb') as out: out.write(body)
        os.replace(temp, FRONTEND / 'library-catalog.json')
    print(json.dumps({'sources': len(catalog['sources']), 'objects': len(catalog['artifacts']),
                      'payloads': sum(bool(a['payload']) for a in catalog['artifacts']), 'activated': args.activate}))
