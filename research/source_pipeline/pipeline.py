"""Incremental local acquisition and ingestion preparation. No AWS SDK or production imports."""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import date
import io
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urljoin, urlsplit, urldefrag
import uuid

from register import read_register, sha
from network import Client, now, safe_url
from extract import extract, SERIES, cover_report_year

ROOT = Path(__file__).resolve().parent
RESEARCH = ROOT.parent
OLD = RESEARCH / 'source_documents'
OLD_RUN = OLD / 'runs/20261115T131702Z_d4fbb4fa'
FRED = {'SRC-030': 'DCOILBRENTEU', 'SRC-031': 'DCOILWTICO', 'SRC-043': 'T10YIE', 'SRC-044': 'DGS10', 'SRC-045': 'DGS2'}
API_IDS = {'SRC-032', 'SRC-040', 'SRC-049'}
STRUCTURED_IDS = set(FRED) | {'SRC-001', 'SRC-002', 'SRC-003', 'SRC-004', 'SRC-037', 'SRC-040'}
PORTALS = {'SRC-032', 'SRC-033', 'SRC-039', 'SRC-046', 'SRC-047', 'SRC-048', 'SRC-049', 'SRC-050'}
NARRATIVE_PAGES = {'SRC-005', 'SRC-006', 'SRC-008', 'SRC-016', 'SRC-034', 'SRC-035', 'SRC-036', 'SRC-038', 'SRC-041', 'SRC-042', 'SRC-051', 'SRC-052'}


def immutable(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw: raise ValueError('Refusing to overwrite immutable artifact')
    else:
        with path.open('xb') as out: out.write(raw)


def write_json(path, data):
    immutable(path, (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode())


def status_summary(entries):
    counts = Counter(e['usability'] for e in entries)
    return {'register_entries': len(entries), 'counts': dict(counts),
            'usable_for_intended_research': counts['usable'],
            'context_only': counts['context_only'], 'needs_attention': len(entries) - counts['usable'],
            'sources_with_extracted_content': sum(any(a.get('extraction_status') == 'extracted' for a in e['artifacts']) for e in entries),
            'sources_with_new_downloads': sum(any(a.get('retrieval_status') == 'downloaded' for a in e['artifacts']) for e in entries),
            'sources_with_reused_artifacts': sum(any(a.get('retrieval_status', '').startswith('reused') for a in e['artifacts']) for e in entries)}


class Workflow:
    def __init__(self, storage, client=None, refresh=False, discover_pending=False):
        self.storage = Path(storage); self.client = client or Client(); self.refresh = refresh
        self.discover_pending = discover_pending
        self.run = self.storage / 'runs' / (now().replace(':', '').replace('.', '') + '_' + uuid.uuid4().hex[:6])
        self.run.mkdir(parents=True)
        self.previous = None; self.cached = {}; self.extractions = {}; self.entry_cache = {}
        for p in sorted((self.storage / 'runs').glob('*/inventory.json')):
            self.previous = json.loads(p.read_text())
            for e in self.previous['sources']:
                for a in e['artifacts']:
                    if a.get('sha256') and a.get('blob'):
                        self.cached[a.get('original_url')] = a
        # Completed per-source receipts survive interruptions before the final inventory is written.
        for p in sorted((self.storage / 'runs').glob('*/receipts/SRC-*.json')):
            e = json.loads(p.read_text()); e['reused_from_run'] = p.parents[1].name
            self.entry_cache[e['source_id']] = e
            for a in e['artifacts']:
                if a.get('sha256') and a.get('blob'): self.cached[a.get('original_url')] = a

    def store(self, body):
        digest = sha(body); p = self.storage / 'objects' / digest
        immutable(p, body)
        return digest, str(p.relative_to(self.storage))

    def enrich(self, a, entry):
        path = self.storage / a['blob']
        if sha(path.read_bytes()) != a['sha256']: raise ValueError('Stored object hash conflict')
        series = FRED.get(entry['ID'])
        key = (a['sha256'], series)
        try:
            if key not in self.extractions: self.extractions[key] = extract(path, series)
            ext = self.extractions[key]
            # All materialized extractions are immutable and tied to original bytes + adapter version.
            xp = self.storage / 'extracted' / f"{a['sha256']}_{series or 'generic'}_v3.json"
            write_json(xp, ext)
            a.update(extraction_status='extracted', extraction_file=str(xp.relative_to(self.storage)), actual_format=ext['kind'])
            a.pop('extraction_error', None)
            a['date_range'] = {'min': ext.get('date_min'), 'max': ext.get('date_max')}
            a['row_count'] = ext.get('row_count'); a['page_count'] = ext.get('page_count')
            a['units'] = ext.get('units', [ext.get('unit')] if ext.get('unit') else [])
            a['publication_date_candidates'] = ext.get('publication_date_candidates', [])
            # Preserve a hash-bound explicit identity review across offline refreshes.
            review = a.get('recovery_identity_review', {})
            a['publication_date'] = review.get('publication_date') if review.get('document_sha256') == a['sha256'] else None
            a.setdefault('content_verification', 'UNVERIFIED_extracted_not_reviewed')
            if ext['kind'] == 'pdf':
                cover = ' '.join(p['text'] for p in ext['pages'][:2])[:2500]
                a['observed_title_excerpt'] = ext['pages'][0]['text'][:350]
                requested = re.findall(r'FY(20\d\d)', entry['Period'])
                observed = set(re.findall(r'\b20\d\d\b', cover))
                title_year = cover_report_year(ext['pages'][0]['text'])
                if title_year: observed.add(title_year)
                # A comparison year in introductory prose is not proof of an outdated report.
                if a.get('period_check') == 'outdated_for_requested_period' and not a.get('prior_review') and not a.get('purpose_attention'):
                    a['quarantine'] = False
                a['period_check'] = 'candidate_match_manual_review' if requested and requested[0] in observed else 'UNVERIFIED'
                if requested and title_year and title_year < requested[0]:
                    a['period_check'] = 'outdated_for_requested_period'; a['quarantine'] = True
                compact = lambda s: re.sub(r'[^a-z0-9]', '', s.lower())
                publisher = compact(entry['Publisher'])
                aliases = {'SRC-020': ['torontodominion', 'tdbank'], 'SRC-024': ['banquenationale', 'nationalbank'],
                           'SRC-010': ['canadiannational', 'cninvestor'], 'SRC-022': ['scotiabank', 'bankofnovascotia'],
                           'SRC-023': ['canadianimperialbank', 'cibc']}
                terms = aliases.get(entry['ID'], [publisher])
                matches = [{'pdf_page': p['pdf_page'], 'term': term} for p in ext['pages'][:30] for term in terms if term in compact(p['text'])]
                a['issuer_text_check'] = {'status': 'automated_text_match' if matches else 'UNVERIFIED', 'locations': matches[:3]}
                a['content_verification_scope'] = 'Identity candidates only; citations, financial tables and period semantics require review.'
                if re.search(r'proxy.circular|management.proxy', cover, re.I):
                    a['purpose_attention'] = 'Proxy/governance document, not the requested financial report.'
                    a['quarantine'] = True
            if ext['kind'] in ('time_series', 'holdings', 'statcan_table'):
                a['structure_verification'] = 'parsed_dates_units_and_values'
                a['period_check'] = 'observed_in_data'
                if ext.get('date_max') and len(ext['date_max']) == 10:
                    a['age_days_at_run'] = (date.today() - date.fromisoformat(ext['date_max'])).days
                    if ext['kind'] == 'time_series' and a['age_days_at_run'] > 14:
                        a['freshness_attention'] = 'Latest daily observation older than 14 days; no fill-forward.'
            return a, ext
        except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
            a.update(extraction_status='pending', extraction_error=str(error)[:180])
            return a, None

    def acquire(self, url, entry, allowed, role='registered_source', link_receipt=None):
        url = safe_url(url)
        prior = self.cached.get(url)
        if prior and not self.refresh:
            a = dict(prior, retrieval_status='reused_cache', current_link_status='not_rechecked')
            a['role'] = role
            return self.enrich(a, entry)
        result = self.client.get(url, allowed)
        body = result.get('body')
        receipt = {k: v for k, v in result.items() if k != 'body'}
        a = {'original_url': url, 'final_url': result.get('url', url), 'retrieval_status': result['status'],
             'retrieved_at': result.get('retrieved_at'), 'http_receipt': receipt, 'role': role,
             'publisher': entry['Publisher'], 'requested_title': entry['Title'], 'requested_period': entry['Period'],
             'source_verification': 'UNVERIFIED', 'extraction_status': 'not_extracted', 'sha256': None}
        if body is not None:
            digest, blob = self.store(body); a.update(sha256=digest, blob=blob, bytes=len(body))
            host = urlsplit(a['final_url']).hostname
            origin = urlsplit(entry['Official URL']).hostname
            a['source_verification'] = 'retrieved_from_registered_publisher_host' if host == origin else 'linked_host_requires_identity_review'
            if link_receipt: a['discovery_receipt'] = link_receipt
            self.cached[url] = a
            return self.enrich(a, entry)
        # A failed refresh cannot delete/replace the previous verified object.
        if prior: a['preserved_previous_sha256'] = prior['sha256']
        return a, None

    def reuse_old(self, entry, manifest, specs, reviews, holdings):
        artifacts = []
        for spec in specs:
            if entry['ID'] not in spec['register_ids']: continue
            old = next((e for e in manifest['entries'] if e['id'] == spec['id']), None)
            if not old or old.get('download_status') != 'downloaded': continue
            p = (OLD / old['local_file']).resolve()
            if not p.is_relative_to(OLD.resolve()): raise ValueError('Previous receipt escapes acquisition workspace')
            body = p.read_bytes()
            if sha(body) != old['sha256']: raise ValueError('Previously acquired PDF hash mismatch')
            digest, blob = self.store(body)
            review = next((r for r in reviews['reviews'] if r['source_id'] == spec['id']), {})
            quarantine = spec['id'] in ('ENB_2025_EN', 'CPKC_2025_EN')
            a = dict(original_url=old['official_url'], final_url=old['http_receipt']['final_url'], sha256=digest,
                     blob=blob, bytes=len(body), retrieval_status='reused_verified_bytes', retrieved_at=old['retrieved_at'],
                     checked_at=now(), role='existing_report', publisher=spec['issuer'], title=spec['title'],
                     reporting_period=spec['reporting_period'], fiscal_year_end=spec['fiscal_year_end'],
                     source_verification='pending_issuer_to_cdn' if spec['id'] == 'CPKC_2025_EN' else 'reported_by_previous_acquisition',
                     content_verification=review.get('metadata_review_status', 'UNVERIFIED'),
                     prior_review=review, quarantine=quarantine, current_link_status='not_rechecked')
            if spec['id'] == 'ENB_2025_EN': a['attention'] = 'Cover says 2024 management circular; inner filing says FY2025. Mixed identity unresolved.'
            a, ext = self.enrich(a, entry); artifacts.append(a); self.cached[a['original_url']] = a
        if entry['ID'] == 'SRC-001' and holdings.is_file():
            body = holdings.read_bytes()
            if sha(body) != '9caae3aa6b3aa4ad4faf2b37c9f96fd604f2a10c8cb60831f388ad0a28947527': raise ValueError('XIU supplied snapshot differs from reviewed hash')
            digest, blob = self.store(body)
            a = dict(original_url=entry['Official URL'], final_url=None, sha256=digest, blob=blob, bytes=len(body),
                     retrieval_status='reused_verified_bytes', retrieved_at=None, checked_at=now(), role='existing_holdings',
                     publisher=entry['Publisher'], source_verification='provided_snapshot_online_byte_match_UNVERIFIED',
                     content_verification='holdings_snapshot_identity_from_team_and_hash', quarantine=False)
            a, _ = self.enrich(a, entry); artifacts.append(a)
        return artifacts

    def run_entry(self, entry, manifest, specs, reviews, holdings):
        e = {'source_id': entry['ID'], 'register': entry, 'artifacts': [], 'attention': [], 'aws_status': 'NOT_CHECKED'}
        e['expected_kind'] = 'api_dataset' if entry['ID'] in API_IDS else 'csv_dataset' if entry['ID'] in STRUCTURED_IDS else 'pdf_report' if '.pdf' in entry['Official URL'].lower() else 'official_web_page'
        e['artifacts'] = self.reuse_old(entry, manifest, specs, reviews, holdings)
        allowed = {urlsplit(entry['Official URL']).hostname}
        allowed |= {h for s in specs if entry['ID'] in s['register_ids'] for h in s['allowed_hosts']}
        allowed |= {host[4:] if host.startswith('www.') else 'www.' + host for host in list(allowed)}
        a, ext = self.acquire(entry['Official URL'], entry, allowed)
        if not any(x.get('sha256') == a.get('sha256') and a.get('sha256') for x in e['artifacts']): e['artifacts'].append(a)
        extra = []
        sid = FRED.get(entry['ID'])
        if sid:
            extra.append((f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd=2021-11-12&coed=2026-11-15', 'documented_FRED_CSV_endpoint'))
        if entry['ID'] == 'SRC-002':
            extra.append((entry['Official URL'] + '/1464253357814.ajax?fileType=csv&fileName=XESG_holdings&dataType=fund', 'existing_ingest_export_endpoint'))
        if entry['ID'] == 'SRC-040':
            extra.append(('https://www.bankofcanada.ca/valet/observations/FXUSDCAD,BD.CDN.10YR.DQ.YLD,BD.CDN.2YR.DQ.YLD/json?start_date=2021-11-12&end_date=2026-11-15', 'documented_Valet_observations_endpoint'))
        if entry['ID'] == 'SRC-037':
            extra.append(('https://www150.statcan.gc.ca/t1/wds/rest/getFullTableDownloadCSV/18100001/en', 'documented_StatCan_WDS_download_endpoint'))
        # One-hop discovery only: exact hrefs, requested years, finite limit; no speculative crawling.
        if ext and ext['kind'] == 'html':
            requested_years = re.findall(r'20\d\d', entry['Period'])
            candidates = []
            for link in ext['links']:
                url = urldefrag(urljoin(a['final_url'], link['href']))[0]
                text = (link['text'] + ' ' + url).lower()
                if not url.startswith('https:') or url == a['final_url']: continue
                file = re.search(r'\.pdf(?:\?|$)|\.csv(?:\?|$)|\.xlsx(?:\?|$)|filetype=csv', url, re.I) or 'pdf' in link['text'].lower()
                if not file: continue
                if re.search(r'proxy|circular|speech|presentation', text): continue
                if entry['ID'] in STRUCTURED_IDS and ('holding' in text or '.csv' in text): candidates.append((url, 'exact_registered_page_href'))
                elif any(year in text for year in requested_years) and re.search(r'annual|rapport|aif|10-k|10k|quarter|q3|fact|methodolog|outlook', text):
                    candidates.append((url, 'exact_registered_page_href'))
            known_hashes = {x.get('original_url') for x in e['artifacts'] if x.get('sha256')}
            ranked = sorted(dict.fromkeys(candidates), key=lambda pair: (0 if re.search(r'annual[-_ %]+report', pair[0], re.I) else 1 if re.search(r'information[-_ %]+form|aif', pair[0], re.I) else 2, pair[0]))
            for pair in ranked:
                if pair[0] not in known_hashes: extra.append(pair)
                if len(extra) >= 3: break
            e['discovered_file_links'] = len(set(u for u, _ in candidates))
        for url, role in extra[:3]:
            host = urlsplit(url).hostname
            public_cdn = host and (any(host.endswith('.' + domain) for domain in ('q4cdn.com', 'ctfassets.net', 'investorroom.com'))
                                  or host in {'shopifyinvestors.gcs-web.com', 'mc-3405db07-6660-4b4e-8bc8-1763-cdn-endpoint.azureedge.net'})
            same_publisher_subdomain = host and host.endswith('.' + urlsplit(entry['Official URL']).hostname.removeprefix('www.'))
            if host not in allowed and not public_cdn and not same_publisher_subdomain:
                e['attention'].append('Discovered file host needs review: ' + str(host)); continue
            item, extracted = self.acquire(url, entry, allowed | {host}, role,
                                           {'parent_url': a.get('final_url'), 'parent_sha256': a.get('sha256'), 'method': role})
            e['artifacts'].append(item)
            if entry['ID'] == 'SRC-037' and extracted and extracted['kind'] == 'json_metadata':
                response = extracted['data']
                if isinstance(response, list) and response: response = response[0]
                link = response.get('object') if isinstance(response, dict) and response.get('status') == 'SUCCESS' else None
                if isinstance(link, str) and urlsplit(link).hostname in ('www150.statcan.gc.ca', 'www.statcan.gc.ca'):
                    item2, _ = self.acquire(link, entry, {urlsplit(link).hostname}, 'WDS_returned_download_URL',
                                            {'parent_url': url, 'parent_sha256': item['sha256']})
                    e['artifacts'].append(item2)
        if self.previous:
            previous = next((x for x in self.previous['sources'] if x['source_id'] == entry['ID']), None)
            if previous:
                present = {a.get('sha256') for a in e['artifacts']}
                for old in previous['artifacts']:
                    if old.get('sha256') and old['sha256'] not in present:
                        e['artifacts'].append(dict(old, retrieval_status='reused_previous_version', current_link_status='not_rechecked'))
        usable = []
        for item in e['artifacts']:
            k = item.get('actual_format')
            eligible = item.get('extraction_status') == 'extracted' and not item.get('quarantine')
            if eligible and k in ('holdings', 'time_series', 'statcan_table'): usable.append(item)
            if eligible and k == 'zip_csv':
                ex = json.loads((self.storage / item['extraction_file']).read_text())
                if any(m['data']['kind'] == 'statcan_table' for m in ex['members']): usable.append(item)
            if eligible and k == 'pdf' and item.get('period_check') != 'outdated_for_requested_period': usable.append(item)
            if eligible and k == 'html' and entry['ID'] in NARRATIVE_PAGES: usable.append(item)
        e['usability'] = 'usable' if usable else 'context_only' if any(a.get('extraction_status') == 'extracted' and not a.get('quarantine') for a in e['artifacts']) else 'needs_attention'
        e['scope_completeness'] = 'not_exhaustively_verified; entries may request several reports or datasets'
        if entry['ID'] in PORTALS: e['attention'].append('Portal/documentation captured if accessible; actual filing/dataset selection still required.')
        if entry['ID'] == 'SRC-032': e['attention'].append('EIA API key and precise route/series selection required. No key requested or used.')
        if entry['ID'] == 'SRC-049': e['attention'].append('SEC companyfacts requires reviewed CIKs and compliant requester identity; no bulk issuer facts requested.')
        for item in e['artifacts']:
            if item.get('quarantine'): e['attention'].append(item.get('attention', 'Source provenance pending; excluded from ready staging.'))
            if item.get('freshness_attention'): e['attention'].append(item['freshness_attention'])
        if not usable: e['attention'].append('No qualified report/dated dataset for intended use; a landing page is not a substitute.')
        return e

    def stage(self, entries):
        documents = {}; structured = []
        for e in entries:
            for a in e['artifacts']:
                if a.get('extraction_status') != 'extracted': continue
                d = documents.setdefault(a['sha256'], {'artifact': a, 'source_ids': [], 'quarantine': a.get('quarantine', False)})
                d['source_ids'].append(e['source_id']); d['quarantine'] |= a.get('quarantine', False)
        files = []; quarantined = 0; mappings = []
        for digest, d in documents.items():
            a = d['artifact']; ex = json.loads((self.storage / a['extraction_file']).read_text())
            branch = 'quarantine' if d['quarantine'] else 'review_required'
            if d['quarantine']: quarantined += 1
            if ex['kind'] in ('pdf', 'html'):
                pages = ex.get('pages', [{'pdf_page': None, 'text': ex.get('text', '')}])
                for page in pages:
                    text = page['text']
                    for start in range(0, len(text), 10000):
                        segment = text[start:start + 10000]
                        if not segment.strip(): continue
                        name = f"{digest}_p{page['pdf_page'] or 'html'}_c{start}.txt"
                        p = self.run / 'kb_preparation' / branch / name
                        immutable(p, segment.encode())
                        attrs = {'document_sha256': digest, 'source_ids': ','.join(sorted(set(d['source_ids']))),
                                 'source_url': a.get('original_url') or '', 'issuer': a.get('publisher', ''),
                                 'document_title': a.get('title') or ex.get('title') or a.get('requested_title', 'UNVERIFIED'),
                                 'reporting_period_label': a.get('reporting_period') or a.get('requested_period', 'UNVERIFIED'),
                                 'source_verification': a.get('source_verification', 'UNVERIFIED'),
                                 'content_verification': a.get('content_verification', 'UNVERIFIED'),
                                 'stock_return_direction': 'unknown', 'record_kind': 'source_text_not_verified_evidence',
                                 'source_purpose': 'navigation_or_API_documentation' if all(i in PORTALS for i in d['source_ids']) else 'research_source',
                                 'citation_approved': False,
                                 'char_start': start, 'char_end': start + len(segment)}
                        if page['pdf_page'] is not None: attrs['pdf_page'] = page['pdf_page']
                        if a.get('publication_date'): attrs['publication_date'] = a['publication_date']
                        write_json(Path(str(p) + '.metadata.json'), {'metadataAttributes': attrs})
                        files.append(str(p.relative_to(self.run)))
            else:
                p = self.run / 'structured_preparation' / f'{digest}.json'
                write_json(p, {'source_ids': sorted(set(d['source_ids'])), 'source_sha256': digest,
                               'source_url': a.get('original_url'), 'data': ex, 'pipeline_status': 'local_only_review_required'})
                structured.append(str(p.relative_to(self.run)))
                # Exact original FRED/holdings CSVs match existing raw readers; no production write.
                if ex['kind'] == 'holdings' or (ex['kind'] == 'time_series' and len(ex.get('source_columns', [])) == 2):
                    rel = f"raw_compatible/{digest}.csv"
                    immutable(self.run / rel, (self.storage / a['blob']).read_bytes())
                    sid = next((FRED[i] for i in d['source_ids'] if i in FRED), None)
                    holdings_name = 'xiu' if 'SRC-001' in d['source_ids'] else 'xesg' if 'SRC-002' in d['source_ids'] else 'unmapped_fund'
                    mappings.append({'local_file': rel, 'source_sha256': digest,
                                     'proposed_raw_path': f'raw/fred/snapshot=<approved_date>/{sid}.csv' if sid else f'raw/holdings/snapshot=<approved_date>/{holdings_name}_holdings.csv',
                                     'contract_status': 'existing_reader' if sid in ('DCOILBRENTEU', 'T10YIE') or holdings_name in ('xiu', 'xesg') else 'extension_requires_approval'})
                if ex['kind'] == 'time_series' and ex.get('series_metadata'):
                    fx = [v for v in ex['records'] if v['series_id'] == 'FXUSDCAD' and v['value'] is not None]
                    rates = [v for v in ex['records'] if v['series_id'].startswith('BD.CDN.')]
                    from decimal import Decimal
                    for filename, columns, rows in [
                        ('fx_usdcad_daily.csv', ['date', 'usdcad', 'cadusd'],
                         [{'date': v['date'], 'usdcad': v['value'], 'cadusd': str(Decimal(1) / Decimal(v['value']))} for v in fx if Decimal(v['value']) > 0]),
                        ('macro_rates.csv', ['date', 'series_id', 'value', 'unit', 'frequency', 'label', 'source'],
                         [{**v, 'source': a['original_url']} for v in rates])]:
                        if not rows: continue
                        buffer = io.StringIO(); w = csv.DictWriter(buffer, fieldnames=columns); w.writeheader(); w.writerows(rows)
                        rel = f'raw_compatible/{digest}/{filename}'; immutable(self.run / rel, buffer.getvalue().encode())
                        mappings.append({'local_file': rel, 'source_sha256': digest, 'proposed_raw_path': 'raw/starter/' + filename,
                                         'contract_status': 'schema_compatible_review_required',
                                         'note': 'No overwrite. FX inverse = 1/usdcad; missing/nonpositive FX omitted and retained in extracted source. Rates are partial (Canada only); never replace a complete macro panel.'})
        result = {'mode': 'LOCAL_ONLY_NOT_APPROVED_FOR_AWS', 'knowledge_base_text_files': len(files),
                  'quarantined_documents': quarantined, 'structured_files': structured, 'text_files': files, 'pipeline_mappings': mappings,
                  'requirements': ['Review content identity and publication dates', 'Clear provenance conflicts and redistribution terms',
                                   'Use separate versioned KB prefixes; do not call compute/evidence.py delete-first publisher',
                                   'Approve unit/schema/date mapping and point-in-time vintage before compute',
                                   'Preserve extraction pages; printed pages and candidate quotations need independent validation']}
        write_json(self.run / 'ingestion_preparation.json', result)
        return result

    def execute(self, register, holdings, original_inventory):
        sources, register_hash = read_register(register)
        manifest = json.loads((OLD_RUN / 'manifest.json').read_text())
        specs = json.loads((OLD / 'priority_sources.json').read_text())
        reviews = json.loads((OLD_RUN / 'metadata_review.json').read_text())
        original = json.loads(original_inventory.read_text())
        entries = []; urls = {}; hashes = defaultdict(list)
        for source in sources:
            prior = self.entry_cache.get(source['ID'])
            rediscover = self.discover_pending and source['ID'] in {'SRC-003', 'SRC-017', 'SRC-028', 'SRC-029'}
            if prior and not self.refresh and prior['register'] == source and not rediscover:
                e = json.loads(json.dumps(prior))
                for i, artifact in enumerate(e['artifacts']):
                    if artifact.get('sha256'):
                        artifact.setdefault('original_retrieval_status', artifact['retrieval_status'])
                        artifact['retrieval_status'] = 'reused_checkpoint'
                        e['artifacts'][i], _ = self.enrich(artifact, source)
                # An adapter improvement can make previously captured data usable, without a new GET.
                if any(a.get('extraction_status') == 'extracted' and not a.get('quarantine') and a.get('actual_format') in ('holdings', 'time_series', 'statcan_table', 'pdf', 'zip_csv') for a in e['artifacts']):
                    e['usability'] = 'usable'
                    e['attention'] = [x for x in e['attention'] if not x.startswith('No qualified')]
            else:
                e = self.run_entry(source, manifest, specs, reviews, holdings)
            url = source['Official URL']
            if url in urls: e['duplicate_register_url_of'] = urls[url]
            else: urls[url] = e['source_id']
            for a in e['artifacts']:
                if a.get('sha256'): hashes[a['sha256']].append(e['source_id'])
            entries.append(e)
            write_json(self.run / 'receipts' / (e['source_id'] + '.json'), e)
            print(f"{e['source_id']}: {e['usability']} | " + ', '.join(a['retrieval_status'] + '/' + a.get('actual_format', 'none') for a in e['artifacts']), flush=True)
        staged = self.stage(entries)
        summary = status_summary(entries)
        summary.update(unique_content_objects=len(hashes), kb_text_files=staged['knowledge_base_text_files'],
                       structured_preparation_files=len(staged['structured_files']))
        result = {'schema_version': 1, 'run_id': self.run.name, 'completed_at': now(),
                  'register_sha256': register_hash, 'original_inventory_sha256': sha(original_inventory.read_bytes()),
                  'original_inventory_profile_claims_UNVERIFIED_in_this_run': original.get('profile'),
                  'previous_run_id': self.previous.get('run_id') if self.previous else None,
                  'summary': summary, 'sources': entries,
                  'duplicate_content': {h: sorted(set(ids)) for h, ids in hashes.items() if len(set(ids)) > 1},
                  'status_definitions': {'usable': 'At least one extracted non-quarantined report, mapped dataset, or relevant narrative page; not complete verification or complete entry coverage.',
                                         'context_only': 'Accessible extraction, but only navigation/docs/unsupported data; desired financial content still missing.',
                                         'needs_attention': 'No qualifying accessible material, or only quarantined material.'},
                  'aws': 'NOT_CONTACTED', 'financial_citations_automatically_verified': False}
        write_json(self.run / 'inventory.json', result)
        robots = {origin: {k: v for k, v in receipt.items() if k != 'body'} for origin, (receipt, _) in self.client.robots.items()}
        for origin, (receipt, _) in self.client.robots.items():
            if receipt.get('body'):
                h, path = self.store(receipt['body']); robots[origin].update(sha256=h, blob=path)
        write_json(self.run / 'robots_receipts.json', robots)
        self.report(result)
        return result

    def report(self, result):
        out = io.StringIO(); fields = ['source_id', 'publisher', 'title', 'usability', 'retrieval', 'formats', 'attention']
        writer = csv.DictWriter(out, fieldnames=fields); writer.writeheader()
        lines = ['# RIPPLE — actual acquisition inventory', '', 'Local-only results. “Usable” means inspectable source material, not verified financial evidence or complete fulfilment of a multi-document entry.', '',
                 '```json', json.dumps(result['summary'], indent=2), '```', '', '| ID | Publisher | Result | Formats | Attention |', '|---|---|---|---|---|']
        for e in result['sources']:
            states = sorted(set(a['retrieval_status'] for a in e['artifacts']))
            formats = sorted({a['actual_format'] for a in e['artifacts'] if a.get('actual_format')})
            attention = e['attention'] + [a.get('http_receipt', {}).get('reason', a['retrieval_status']) for a in e['artifacts'] if not a.get('sha256')]
            if e.get('duplicate_register_url_of'): attention.append('Duplicate URL: ' + e['duplicate_register_url_of'])
            row = dict(source_id=e['source_id'], publisher=e['register']['Publisher'], title=e['register']['Title'],
                       usability=e['usability'], retrieval='; '.join(states), formats=', '.join(formats), attention='; '.join(attention))
            writer.writerow(row)
            lines.append('| ' + ' | '.join(str(row[k]).replace('|', '/') for k in ('source_id', 'publisher', 'usability', 'formats', 'attention')) + ' |')
        immutable(self.run / 'inventory.csv', out.getvalue().encode())
        immutable(self.run / 'REPORT.md', ('\n'.join(lines) + '\n').encode())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--register', type=Path, required=True)
    parser.add_argument('--holdings', type=Path, required=True)
    parser.add_argument('--original-inventory', type=Path, required=True)
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--discover-pending', action='store_true', help='Revisit cached pages for reviewed missing download formats/hosts; never bypass denials')
    parser.add_argument('--offline', action='store_true', help='Only reuse checkpoints; all network calls disabled')
    args = parser.parse_args()
    if args.offline and args.refresh: parser.error('--offline and --refresh are incompatible')
    workflow = Workflow(ROOT / 'artifacts', client=Client(offline=args.offline), refresh=args.refresh, discover_pending=args.discover_pending)
    result = workflow.execute(args.register, args.holdings, args.original_inventory)
    print(json.dumps({'summary': result['summary'], 'run': str(workflow.run)}, indent=2), flush=True)


if __name__ == '__main__': main()
