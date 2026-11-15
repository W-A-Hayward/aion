"""Offline reconciliation of all inventory objects and staged text against source offsets."""
from collections import Counter
import csv
import io
import json
from pathlib import Path

from pipeline import ROOT, immutable, write_json
from register import sha


def audit(run):
    storage = run.parents[1]
    data = json.loads((run / 'inventory.json').read_text())
    assert len(data['sources']) == 52
    artifacts = {}; rows = []
    for e in data['sources']:
        for a in e['artifacts']:
            h = a.get('sha256')
            if h:
                assert sha((storage / a['blob']).read_bytes()) == h, 'Object bytes changed'
                artifacts[h] = a
            rows.append({
                'source_id': e['source_id'], 'publisher': a.get('publisher', e['register']['Publisher']),
                'requested_title': e['register']['Title'], 'observed_title': a.get('title', a.get('observed_title_excerpt', '')),
                'requested_period': e['register']['Period'], 'publication_date': a.get('publication_date'),
                'original_url': a.get('original_url'), 'final_url': a.get('final_url'), 'retrieved_at': a.get('retrieved_at'),
                'sha256': h, 'local_object': a.get('blob'), 'actual_format': a.get('actual_format'),
                'retrieval_status': a['retrieval_status'], 'original_retrieval_status': a.get('original_retrieval_status'),
                'extraction_status': a.get('extraction_status'), 'extraction_error': a.get('extraction_error'),
                'date_min': a.get('date_range', {}).get('min'), 'date_max': a.get('date_range', {}).get('max'),
                'units': json.dumps(a.get('units', [])), 'source_verification': a.get('source_verification'),
                'content_verification': a.get('content_verification'), 'byte_hash_check': 'verified_locally' if h else 'unavailable',
                'quarantine': a.get('quarantine', False),
            })
    prep = json.loads((run / 'ingestion_preparation.json').read_text())
    checked = 0; branches = Counter(); extractions = {}
    for rel in prep['text_files']:
        p = run / rel; meta = json.loads(Path(str(p) + '.metadata.json').read_text())['metadataAttributes']
        h = meta['document_sha256']; a = artifacts[h]
        if h not in extractions: extractions[h] = json.loads((storage / a['extraction_file']).read_text())
        x = extractions[h]
        if 'pdf_page' in meta:
            original = next(page['text'] for page in x['pages'] if page['pdf_page'] == meta['pdf_page'])
        else: original = x['text']
        assert p.read_text() == original[meta['char_start']:meta['char_end']], 'Staged text differs from extraction'
        assert meta['stock_return_direction'] == 'unknown' and meta['citation_approved'] is False
        assert 'printed_page' not in meta
        checked += 1; branches[Path(rel).parts[1]] += 1
    for rel in prep['structured_files']:
        obj = json.loads((run / rel).read_text()); assert obj['source_sha256'] in artifacts
    formats = Counter(a.get('actual_format', 'extraction_pending') for a in artifacts.values())
    result = {'run_id': data['run_id'], 'source_entries': 52, 'verified_content_hashes': len(artifacts),
              'unique_object_formats': dict(formats), 'verified_staged_text_segments': checked,
              'segments_by_review_status': dict(branches), 'structured_preparations': len(prep['structured_files']),
              'contract_mappings': len(prep['pipeline_mappings']),
              'original_downloaded_object_count': sum(bool(a.get('http_receipt')) for a in artifacts.values()),
              'objects_reused_from_preexisting_files': sum(not a.get('http_receipt') for a in artifacts.values()),
              'automatic_financial_citation_approvals': 0, 'network_used_for_audit': False}
    result['duplicate_register_urls'] = {e['source_id']: e['duplicate_register_url_of'] for e in data['sources'] if e.get('duplicate_register_url_of')}
    result['same_entry_duplicate_bytes'] = {e['source_id']: [h for h, n in Counter(a.get('sha256') for a in e['artifacts'] if a.get('sha256')).items() if n > 1] for e in data['sources']}
    result['same_entry_duplicate_bytes'] = {k: v for k, v in result['same_entry_duplicate_bytes'].items() if v}
    write_json(run / 'offline_audit.json', result)
    out = io.StringIO(); w = csv.DictWriter(out, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    immutable(run / 'artifact_inventory.csv', out.getvalue().encode())
    print(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    audit(sorted((ROOT / 'artifacts/runs').glob('*/inventory.json'))[-1].parent)
