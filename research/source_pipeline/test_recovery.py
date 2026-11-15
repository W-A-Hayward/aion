import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import subprocess

from extract import csv_extract
from network import Client
from pipeline import Workflow
from recovery import read_bundle, validate_extraction, integrate, publisher_link
from review_recovery import reviewed_inventory


def fred_row():
    return {'id': 'SRC-030', 'name': 'Brent', 'period': '2021-11-12/2026-11-15',
            'kind': 'fred_csv', 'url': 'https://fred.stlouisfed.org/test.csv',
            'publisher_page': 'https://fred.stlouisfed.org/series/DCOILBRENTEU'}


class RecoveryTests(unittest.TestCase):
    def test_actual_identity_reviews_preserve_prior_quarantines_and_require_exact_hashes_and_offsets(self):
        root = Path(__file__).resolve().parent
        base = json.loads((root / 'artifacts/runs/2026-11-15T170803132629+0000_7b900f/inventory.json').read_text())
        reviews = json.loads((root / 'recovery_identity_reviews_2026-11-15.json').read_text())['reviews']
        result = reviewed_inventory(base, reviews, root / 'artifacts')
        self.assertEqual(len(result['sources']),52)
        cp = next(e for e in result['sources'] if e['source_id']=='SRC-026')
        self.assertTrue(next(a for a in cp['artifacts'] if a.get('sha256'))['quarantine'])
        for sid in ['SRC-021','SRC-027']:
            e = next(e for e in result['sources'] if e['source_id']==sid)
            self.assertEqual(e['usability'],'context_only')
            a = next(a for a in e['artifacts'] if a.get('sha256'))
            self.assertFalse(a['quarantine']); self.assertIn('financial_claims_UNVERIFIED',a['content_verification'])
        for change in [lambda r:r.update(document_sha256='0'*64), lambda r:r['anchors'][0].update(start=999),
                       lambda r:r.update(citation_approved=True), lambda r:r.update(stock_return_direction='positive')]:
            bad = json.loads(json.dumps(reviews)); change(bad[0])
            with self.assertRaises(ValueError): reviewed_inventory(base,bad,root/'artifacts')
        with self.assertRaises(ValueError): reviewed_inventory(base,[],root/'artifacts')

    def test_same_host_robots_redirect_to_404_is_recorded(self):
        client = Client()
        with patch.object(client, 'raw', side_effect=[{'status': 'redirect', 'url': 'https://example.com/robots.txt', 'redirect_url': 'https://example.com/missing'},
                                                    {'status': 'unavailable_http', 'http_status': 404}]) as raw:
            self.assertEqual(client.allowed('https://example.com/report.pdf'), (True, 'robots_not_published'))
            self.assertEqual(raw.call_count, 2)
            self.assertEqual(len(client.robots['https://example.com'][0]['robots_redirect_chain']), 1)
        other = Client()
        with patch.object(other, 'raw', return_value={'status': 'redirect', 'redirect_url': 'https://other.example/robots.txt'}) as raw:
            self.assertFalse(other.allowed('https://example.com/report.pdf')[0]); self.assertEqual(raw.call_count, 1)

    def test_http2_transport_retry_is_bounded_and_never_retries_denial(self):
        def result(exit_code, code, body=b''):
            return subprocess.CompletedProcess([], exit_code, stdout=body + b'\n__RIPPLE_META__' + json.dumps({'http_code': code}).encode())
        with patch('network.socket.getaddrinfo', return_value=[(None,None,None,None,('8.8.8.8',443))]), patch('network.time.sleep'):
            client = Client()
            with patch('network.subprocess.run', side_effect=[result(92,0),result(0,200,b'body')]) as run:
                self.assertEqual(client.raw('https://example.com/test')['status'],'downloaded')
                self.assertEqual(run.call_count,2); self.assertIn('--http1.1',run.call_args.args[0])
            with patch('network.subprocess.run', return_value=result(0,403)) as run:
                self.assertEqual(client.raw('https://example.com/denied')['status'],'blocked_http'); self.assertEqual(run.call_count,1)

    def test_archive_manifest_is_read_without_executing_supplied_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'bundle.zip'
            with zipfile.ZipFile(p, 'w') as z:
                z.writestr('ripple_source_recovery/source_manifest.json', json.dumps({'sources': [fred_row()]}))
                z.writestr('ripple_source_recovery/collect_sources.py', 'raise RuntimeError("never execute")')
                z.writestr('../../escape', 'not extracted')
            data, _, digest = read_bundle(p, {'SRC-030'})
            self.assertEqual(data['sources'][0]['id'], 'SRC-030'); self.assertEqual(len(digest), 64)
            self.assertEqual(len(list(Path(tmp).iterdir())), 1)

    def test_duplicates_unmatched_parents_and_unsafe_urls_rejected(self):
        variants = [[fred_row(), fred_row()], [dict(fred_row(), parent='SRC-099')],
                    [dict(fred_row(), url='https://127.0.0.1/private')],
                    [dict(fred_row(), kind='alias', alias_of='SRC-099')]]
        for rows in variants:
            with self.subTest(rows=rows), tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / 'bundle.zip'
                with zipfile.ZipFile(p, 'w') as z:
                    z.writestr('ripple_source_recovery/source_manifest.json', json.dumps({'sources': rows}))
                with self.assertRaises(ValueError): read_bundle(p, {'SRC-030'})

    def test_csv_identity_numeric_values_duplicates_and_window(self):
        good = b'observation_date,DCOILBRENTEU\n2021-11-12,80.0\n2022-01-03,.\n2026-11-13,70\n'
        extracted = csv_extract(good, 'DCOILBRENTEU')
        check, qualifies = validate_extraction(fred_row(), extracted, {})
        self.assertTrue(qualifies); self.assertEqual(check['missing_values'], 1)
        self.assertEqual(extracted['records'][1]['value'], None)
        self.assertEqual(check['units'], 'USD/barrel')
        self.assertFalse(check['citation_approved'])
        for invalid in [good.replace(b'80.0', b'NaN'), good.replace(b'80.0', b'word'),
                        good.replace(b'2026-11-13', b'2021-11-12')]:
            with self.assertRaises(ValueError): csv_extract(invalid, 'DCOILBRENTEU')
        wrong = csv_extract(good.replace(b'DCOILBRENTEU', b'DCOILWTICO'), 'DCOILBRENTEU')
        self.assertFalse(validate_extraction(fred_row(), wrong, {})[1])
        outside = csv_extract(good.replace(b'2026-11-13', b'2027-01-01'), 'DCOILBRENTEU')
        with self.assertRaisesRegex(ValueError, 'outside'): validate_extraction(fred_row(), outside, {})
        partial = csv_extract(b'DATE,DCOILBRENTEU\n2026-11-13,70\n', 'DCOILBRENTEU')
        self.assertFalse(validate_extraction(fred_row(), partial, {})[1])

    def test_pdf_format_match_does_not_approve_identity_or_quotations(self):
        row = dict(fred_row(), kind='pdf')
        result, qualifies = validate_extraction(row, {'kind': 'pdf', 'pages': [{'pdf_page': 1, 'text': '2025 report'}]}, {})
        self.assertEqual(result['format'], 'validated'); self.assertFalse(qualifies)
        self.assertEqual(result['financial_claims'], 'UNVERIFIED')

    def test_failed_recovery_preserves_previous_objects_quarantine_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = Workflow(Path(tmp), Client(offline=True))
            old = {'sha256': 'a' * 64, 'quarantine': True, 'original_url': 'https://old.example/cp.pdf'}
            base = {'run_id': 'previous', 'sources': [{'source_id': 'SRC-026', 'register': {'ID': 'SRC-026', 'Publisher': 'CPKC',
                    'Official URL': 'https://www.sec.gov/filing'}, 'usability': 'needs_attention', 'artifacts': [old], 'attention': ['pending']}]}
            row = dict(fred_row(), id='SRC-026', kind='html', url='https://www.sec.gov/filing')
            result = integrate(w, base, [row])
            self.assertEqual(result['sources'][0]['artifacts'][0], old)
            self.assertEqual(result['sources'][0]['usability'], 'needs_attention')
            self.assertEqual(len(base['sources'][0]['artifacts']), 1)
            self.assertEqual(result['sources'][0]['recovery_candidates'][0]['status'], 'pending_offline')
            self.assertEqual(w.client.requests, 0)

    def test_alias_does_not_reassign_cpkc_evidence_to_edgar_portal(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = Workflow(Path(tmp), Client(offline=True))
            base = {'run_id': 'previous', 'sources': [{'source_id': 'SRC-048', 'artifacts': [], 'usability': 'needs_attention'}]}
            row = dict(fred_row(), id='SRC-048', kind='alias', alias_of='SRC-026')
            with patch.object(w, 'acquire') as get:
                result = integrate(w, base, [row]); get.assert_not_called()
            self.assertEqual(result['sources'][0]['artifacts'], [])
            self.assertEqual(result['sources'][0]['recovery_candidates'][0]['related_source'], 'SRC-026')

    def test_partial_recheck_preserves_other_candidates_and_previous_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = Workflow(Path(tmp), Client(offline=True))
            old = {'id':'SRC-048','status':'old_check','checked_at':'earlier'}
            base = {'run_id':'previous','sources':[
                {'source_id':'SRC-048','artifacts':[],'recovery_candidates':[old]},
                {'source_id':'SRC-049','artifacts':[],'recovery_candidates':[{'id':'SRC-049','status':'deferred_backend_work'}]}]}
            result=integrate(w,base,[dict(fred_row(),id='SRC-048',kind='alias',alias_of='SRC-026')])
            self.assertEqual(result['recovery_summary']['candidates'],2)
            self.assertEqual(result['recovery_summary']['checked_this_run'],1)
            self.assertEqual(result['sources'][1],base['sources'][1])
            self.assertEqual(result['sources'][0]['recovery_candidates'][0]['previous_checks'],[old])

    def test_incremental_enrichment_keeps_hash_bound_review_date(self):
        from register import sha
        with tempfile.TemporaryDirectory() as tmp:
            w=Workflow(Path(tmp),Client(offline=True)); h,blob=w.store(b'<html>' + b'Substantive report text. ' * 10 + b'</html>')
            a={'sha256':h,'blob':blob,'recovery_identity_review':{'document_sha256':h,'publication_date':'2026-02-12'}}
            e={'ID':'SRC-027','Publisher':'Fortis','Period':'FY2025'}
            enriched,_=w.enrich(a,e)
            self.assertEqual(enriched['publication_date'],'2026-02-12')
            a['recovery_identity_review']['document_sha256']='0'*64
            enriched,_=w.enrich(a,e);self.assertIsNone(enriched['publication_date'])

    def test_publisher_link_requires_exact_href_not_document_mention(self):
        row = fred_row()
        with tempfile.TemporaryDirectory() as tmp:
            client = Client(offline=True)
            response = {'status': 'downloaded', 'body': b'<html><a href="/test.csv">Download</a></html>',
                        'url': row['publisher_page'], 'retrieved_at': '2026-11-15'}
            with patch.object(client, 'get', return_value=response):
                self.assertEqual(publisher_link(client, row, {}, Path(tmp))['status'], 'exact_href_observed')
            response['body'] = b'<html>Brent is available. https://fred.stlouisfed.org/test.csv</html>'
            with patch.object(client, 'get', return_value=response):
                self.assertEqual(publisher_link(client, row, {}, Path(tmp))['status'], 'exact_href_not_found')


if __name__ == '__main__': unittest.main()
