"""Create a portable, local-only UI fixture from existing research. No network or PDF copies."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESEARCH = ROOT.parent / 'research' / 'evidence_v2'


def build():
    source = RESEARCH / 'xiu_resolution_5_companies.json'
    raw = source.read_bytes()
    data = json.loads(raw)
    assert data['catalog_kind'] == 'research_only'
    assert data['holdings_snapshot']['as_of'] == '2026-11-12'
    documents = []
    for d in data['documents']:
        keys = ['document_id', 'sha256', 'issuer', 'document_title', 'language',
                'fiscal_year', 'fiscal_year_end', 'publication_date', 'source_url',
                'source_url_verified_claim', 'source_verification', 'issuer_verification',
                'local_file_verification', 'publication_date_verification', 'provenance_status']
        doc = {k: d[k] for k in keys if k in d}
        # Only public metadata; never expose workstation paths or diagnostics.
        doc['acquisition'] = {k: d.get('acquisition', {}).get(k) for k in
                              ['retrieved_at', 'original_url', 'final_url', 'current_link_availability']}
        documents.append(doc)
    details = {}
    sidecars = []
    for company in ['rbc', 'cnq', 'cpkc']:
        p = RESEARCH / f'candidates_{company}_2025.verification.json'
        b = p.read_bytes()
        sidecars.append({'file': p.name, 'sha256': hashlib.sha256(b).hexdigest()})
        for c in json.loads(b)['candidates']:
            details[c['evidence_id']] = c
    passages = []
    for p in data['passages']:
        row = dict(p)
        c = details.get(p['evidence_id'])
        if c:
            assert c['company_disclosed_text'] == p['excerpt_original']
            assert c['pdf_page'] == p['pdf_page'] and c['subject_ticker'] == p['subject_ticker']
            row['reading_context'] = {k: c.get(k) for k in
                                      ['form', 'table', 'unit_basis', 'context_before', 'context_after']}
        else:
            row['reading_context'] = None
        passages.append(row)
    return {
        'schema_version': 1, 'mode': 'local_research', 'investigation_ticker': 'XIU.TO',
        'source_artifact': {'file': source.name, 'sha256': hashlib.sha256(raw).hexdigest(),
                            'resolved_at': data['resolved_at'], 'context_sources': sidecars},
        'holdings_snapshot': data['holdings_snapshot'], 'scope': data['scope'],
        'holdings': data['holdings'], 'documents': documents, 'passages': passages,
        'statistical_relationships': data['statistical_relationships'],
    }


if __name__ == '__main__':
    # Deliberately exclusive: review a changed input before replacing the UI snapshot.
    with (ROOT / 'evidence-preview.json').open('x', encoding='utf-8') as f:
        json.dump(build(), f, ensure_ascii=False, indent=2)
        f.write('\n')
