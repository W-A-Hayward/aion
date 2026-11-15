import json
from pathlib import Path
import unittest
from copy import deepcopy

from import_methodology import REVIEWED_HASH, inspect_document, merge_supplied

ROOT = Path(__file__).resolve().parent


class SuppliedMethodologyTests(unittest.TestCase):
    def setUp(self):
        self.raw = (ROOT/'artifacts/objects'/REVIEWED_HASH).read_bytes()
        self.ext = json.loads((ROOT/'artifacts/extracted'/f'{REVIEWED_HASH}_generic_v3.json').read_text())

    def test_actual_cover_edition_is_month_precision_and_future_date_is_separate(self):
        r = inspect_document(self.raw,self.ext)
        self.assertEqual(r['edition']['year_month'],'2026-11')
        self.assertIsNone(r['publication_date']);self.assertIsNone(r['download_date'])
        self.assertEqual(r['source_url_verification'],'UNVERIFIED')
        self.assertIn('2026-12-18',r['temporal_limit']);self.assertIn('2026-11-12',r['temporal_limit'])
        self.assertFalse(r['citation_approved']);self.assertEqual(r['stock_return_direction'],'unknown')
        self.assertEqual(next(a for a in r['anchors'] if a['field']=='tsx60_section')['pdf_page'],16)
        for anchor in r['anchors']:
            p=next(p for p in self.ext['pages'] if p['pdf_page']==anchor['pdf_page'])
            self.assertEqual(p['text'][anchor['start']:anchor['end']],anchor['text'])

    def test_changed_bytes_or_edition_fail_before_import(self):
        with self.assertRaisesRegex(ValueError,'Different PDF'):inspect_document(b'other PDF',self.ext)
        changed=deepcopy(self.ext);changed['pages'][0]['text']=changed['pages'][0]['text'].replace('November 2026','September 2026')
        with self.assertRaisesRegex(ValueError,'anchor missing'):inspect_document(self.raw,changed)

    def test_merge_preserves_existing_records_and_quarantine_without_duplication(self):
        base=json.loads((ROOT/'artifacts/runs/2026-11-15T171032535399+0000_8ccfcb/inventory.json').read_text())
        snapshot=deepcopy(base);r=inspect_document(self.raw,self.ext)
        a={'sha256':REVIEWED_HASH,'quarantine':True}
        result=merge_supplied(base,a,r);again=merge_supplied(result,a,r)
        self.assertEqual(base,snapshot);self.assertEqual(len(result['sources']),52)
        for prior,current in zip(base['sources'],result['sources']):
            if prior['source_id']!='SRC-006':self.assertEqual(prior,current)
        s=next(s for s in again['sources'] if s['source_id']=='SRC-006')
        self.assertEqual(s['usability'],'needs_attention');self.assertEqual(s['artifacts'][-1],a)
        self.assertEqual(sum(x.get('sha256')==REVIEWED_HASH for x in s['artifacts']),1)
        self.assertTrue(s['recovery_candidates'][0]['previous_checks'])
        self.assertEqual(result['recovery_summary']['counts']['supplied_identity_reviewed_provenance_pending'],1)


if __name__=='__main__':unittest.main()
