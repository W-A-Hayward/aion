import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from extract import csv_extract, extract, HTML, numeric, cover_report_year
from network import Client, safe_url
from pipeline import Workflow, immutable, status_summary
from register import read_register, sha


class PipelineTests(unittest.TestCase):
    def test_all_52_rows_and_duplicate_source_url(self):
        p = Path('/Users/leahemidj/Downloads/RIPPLE_Official_Research_Register_2026-11-15.xlsx')
        if not p.exists(): self.skipTest('Team research register not installed')
        rows, digest = read_register(p)
        self.assertEqual(len(rows), 52); self.assertEqual(len(digest), 64)
        self.assertEqual(rows[4]['Official URL'], rows[51]['Official URL'])

    def test_immutable_files_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / 'blob'
            immutable(p, b'first'); immutable(p, b'first')
            with self.assertRaises(ValueError): immutable(p, b'changed')
            self.assertEqual(p.read_bytes(), b'first')

    def test_urls_reject_credentials_private_network_and_untrusted_schemes(self):
        for u in ['file:///etc/passwd', 'http://example.com', 'https://127.0.0.1/',
                  'https://localhost/', 'https://user:pass@example.com/', 'https://example.com/?api_key=secret']:
            with self.subTest(url=u), self.assertRaises(ValueError): safe_url(u)
        self.assertEqual(safe_url('https://www.cn.ca/a.pdf#page=5'), 'https://www.cn.ca/a.pdf')

    def test_http_403_is_not_retried_or_bypassed(self):
        c = Client()
        with patch.object(c, 'allowed', return_value=(True, 'test')), patch.object(c, 'raw', return_value={'status': 'blocked_http', 'http_status': 403, 'url': 'https://example.com/a'}) as fetch:
            r = c.get('https://example.com/a', {'example.com'})
            self.assertEqual(r['status'], 'blocked_http'); self.assertEqual(fetch.call_count, 1)
            c.get('https://example.com/a', {'example.com'}); self.assertEqual(fetch.call_count, 1)

    def test_offline_mode_never_touches_network(self):
        c = Client(offline=True)
        with patch.object(c, 'raw') as fetch:
            self.assertEqual(c.get('https://example.com/a', {'example.com'})['status'], 'pending_offline')
            fetch.assert_not_called()

    def test_interrupted_run_recovers_completed_source_receipts(self):
        with tempfile.TemporaryDirectory() as t:
            folder = Path(t) / 'runs' / 'old' / 'receipts'; folder.mkdir(parents=True)
            a = {'original_url': 'https://example.com/a', 'sha256': 'a' * 64, 'blob': 'objects/a'}
            (folder / 'SRC-001.json').write_text(json.dumps({'source_id': 'SRC-001', 'artifacts': [a]}))
            w = Workflow(t, Client(offline=True))
            self.assertIn('SRC-001', w.entry_cache); self.assertIn('https://example.com/a', w.cached)

    def test_robots_denial_never_fetches_the_target(self):
        c = Client()
        with patch.object(c, 'allowed', return_value=(False, 'robots_disallowed')), patch.object(c, 'raw') as fetch:
            self.assertEqual(c.get('https://example.com/a', {'example.com'})['status'], 'blocked_robots')
            fetch.assert_not_called()

    def test_external_redirect_requires_allowed_host(self):
        c = Client()
        with patch.object(c, 'allowed', return_value=(True, 'test')), patch.object(c, 'raw', return_value={'status': 'redirect', 'redirect_url': 'https://other.example/file'}) as fetch:
            self.assertEqual(c.get('https://example.com/a', {'example.com'})['status'], 'pending_redirect_host')
            self.assertEqual(fetch.call_count, 1)

    def test_http_downgrade_is_recorded_and_does_not_abort_batch(self):
        c = Client()
        with patch.object(c, 'allowed', return_value=(True, 'test')), patch.object(c, 'raw', return_value={'status': 'redirect', 'redirect_url': 'http://example.com/file'}):
            self.assertEqual(c.get('https://example.com/a', {'example.com'})['status'], 'blocked_unsafe_redirect')

    def test_unknown_holding_weight_is_retained_not_zero_or_dropped(self):
        raw = b'Fund Holdings as of,"Nov 12, 2026"\nTicker,Name,Sector,Asset Class,Market Weight\nA,A,Tech,Equity,10\nES,Future,Derivatives,Futures,-\n'
        d = csv_extract(raw)
        self.assertEqual(d['row_count'], 2); self.assertIsNone(d['positions'][1]['weight_pct'])
        self.assertEqual(d['missing_weight_count'], 1); self.assertIsNone(d['total_displayed_weight_pct'])

    def test_fred_units_dates_missing_and_duplicates(self):
        d = csv_extract(b'observation_date,DCOILBRENTEU\n2026-11-12,70.2\n2026-11-13,.\n', 'DCOILBRENTEU')
        self.assertEqual(d['missing_count'], 1); self.assertEqual(d['units'], ['USD/barrel'])
        self.assertEqual(d['date_max'], '2026-11-13')
        with self.assertRaises(ValueError): csv_extract(b'DATE,DGS10\n2026-01-01,1\n2026-01-01,2', 'DGS10')
        with self.assertRaises(ValueError): numeric('NaN')

    def test_letter_spaced_report_year_and_comparative_years_are_not_confused(self):
        self.assertEqual(cover_report_year('2 0 2 5 A N N U A L R E P O R T'), '2025')
        self.assertIsNone(cover_report_year('Introduction: comparing performance with 2024.'))
        self.assertEqual(cover_report_year('Annual Report 2024'), '2024')

    def test_holdings_date_is_original_not_retrieval_date(self):
        raw = b'Fund Holdings as of,"Nov 12, 2026"\n\nTicker,Name,Sector,Asset Class,Weight (%)\nRY,Royal Bank,Financials,Equity,9.58\n'
        d = csv_extract(raw)
        self.assertEqual(d['as_of'], '2026-11-12'); self.assertEqual(d['total_displayed_weight_pct'], '9.58')
        self.assertFalse(d['weights_renormalized'])
        with self.assertRaises(ValueError): csv_extract(raw[raw.index(b'Ticker'):])

    def test_statcan_units_scalars_and_suppression_are_retained(self):
        d = csv_extract(b'REF_DATE,GEO,UOM,SCALAR_FACTOR,VALUE,STATUS\n2026-10,Canada,Cents per litre,units,150.1,\n2026-09,Canada,Cents per litre,units,..,F\n')
        self.assertEqual(d['units'], ['Cents per litre']); self.assertEqual(d['records'][1]['STATUS'], 'F')

    def test_html_text_tables_and_links_not_executed(self):
        p = HTML(); p.feed('<title>Issuer</title><script>stealSecrets()</script><p>Original text</p><a href="doc.pdf">Report</a><table><tr><th>CAD millions</th><td>42</td></tr></table>')
        self.assertNotIn('stealSecrets', p.text); self.assertEqual(p.links[0]['href'], 'doc.pdf')
        self.assertEqual(p.tables, [[['CAD millions', '42']]])

    def test_failed_refresh_preserves_previous_object(self):
        with tempfile.TemporaryDirectory() as t:
            c = Client(); w = Workflow(t, c, refresh=True)
            digest, blob = w.store(b'previous verified bytes')
            w.cached['https://example.com/a'] = {'sha256': digest, 'blob': blob}
            with patch.object(c, 'get', return_value={'status': 'blocked_http', 'http_status': 403}):
                a, ex = w.acquire('https://example.com/a', {'Publisher': 'Issuer', 'Title': 'Title', 'Period': '2025'}, {'example.com'})
            self.assertEqual(a['preserved_previous_sha256'], digest)
            self.assertEqual((Path(t) / blob).read_bytes(), b'previous verified bytes')

    def test_staging_quarantines_unverified_source_and_preserves_page_offsets(self):
        with tempfile.TemporaryDirectory() as t:
            w = Workflow(t)
            body = b'original'; digest, blob = w.store(body)
            p = Path(t) / 'pages.json'; p.write_text(json.dumps({'kind': 'pdf', 'pages': [{'pdf_page': 3, 'text': 'exact original\nquotation'}]}))
            e = {'source_id': 'SRC-026', 'artifacts': [{'sha256': digest, 'extraction_status': 'extracted', 'extraction_file': 'pages.json', 'quarantine': True, 'original_url': 'https://example.com/source'}]}
            result = w.stage([e])
            self.assertEqual(result['quarantined_documents'], 1)
            path = w.run / result['text_files'][0]
            self.assertIn('quarantine', str(path)); self.assertEqual(path.read_text(), 'exact original\nquotation')
            meta = json.loads(Path(str(path) + '.metadata.json').read_text())['metadataAttributes']
            self.assertEqual(meta['pdf_page'], 3); self.assertEqual(meta['stock_return_direction'], 'unknown')
            self.assertNotIn('printed_page', meta)


if __name__ == '__main__': unittest.main()
