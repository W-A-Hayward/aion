"""Offline export checks. Reads acquired local files; writes only temporary bundles."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build_frontend_catalog as exporter

INVENTORY = exporter.ROOT / 'artifacts/runs/2026-11-15T153200689426+0000_2b6a5b/inventory.json'


class FrontendCatalogTests(unittest.TestCase):
    def test_complete_export_is_lossless_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            catalog, body = exporter.build(INVENTORY, target)
            original = json.loads(INVENTORY.read_text())
            self.assertEqual(len(catalog['sources']), 52)
            self.assertEqual(len(catalog['artifacts']), 64)
            self.assertEqual(sum(bool(a['payload']) for a in catalog['artifacts']), 62)
            for entry in catalog['sources']:
                source = next(s for s in original['sources'] if s['source_id'] == entry['id'])
                self.assertEqual(entry['url'], source['register']['Official URL'])
                self.assertEqual(entry['usability'], source['usability'])
            for artifact in catalog['artifacts']:
                if not artifact['payload']:
                    continue
                ref = artifact['payload']; raw = (target / ref['path']).read_bytes()
                self.assertEqual(exporter.sha(raw), ref['sha256'])
                source = next(a for s in original['sources'] for a in s['artifacts'] if a.get('sha256') == artifact['sha256'])
                self.assertEqual(json.loads(raw)['data'], json.loads((INVENTORY.parents[2] / source['extraction_file']).read_text()))
                self.assertFalse(artifact['citation_approved'])
            prior = {str(p): p.stat().st_mtime_ns for p in target.rglob('*') if p.is_file()}
            self.assertEqual(exporter.build(INVENTORY, target)[1], body)
            self.assertEqual(prior, {str(p): p.stat().st_mtime_ns for p in target.rglob('*') if p.is_file()})
            self.assertFalse((target / 'library-catalog.json').exists(), 'build alone cannot activate a catalog')

    def test_conflicting_existing_bundle_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            version = exporter.sha(INVENTORY.read_bytes())
            original = json.loads(INVENTORY.read_text())
            first = original['sources'][0]['artifacts'][0]
            path = target / f'research-data/{version}/{first["sha256"]}.json'
            path.parent.mkdir(parents=True); path.write_bytes(b'previous verified content')
            with self.assertRaisesRegex(ValueError, 'overwrite immutable'):
                exporter.build(INVENTORY, target)
            self.assertEqual(path.read_bytes(), b'previous verified content')

    def test_missing_empty_or_mismatched_catalogs_fail_without_activation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(FileNotFoundError):
                exporter.build(root / 'missing/inventory.json', root / 'frontend')
            run = root / 'artifacts/runs/empty'; run.mkdir(parents=True)
            (run / 'inventory.json').write_text(json.dumps({'sources': [], 'run_id': 'empty'}))
            (run / 'offline_audit.json').write_text(json.dumps({'source_entries': 52, 'run_id': 'empty'}))
            with self.assertRaisesRegex(ValueError, 'complete, audited'):
                exporter.build(run / 'inventory.json', root / 'frontend')
            with patch.object(exporter, 'sha', return_value='0' * 64):
                with self.assertRaisesRegex(ValueError, 'Original source hash mismatch'):
                    exporter.build(INVENTORY, root / 'frontend')
            self.assertFalse((root / 'frontend/library-catalog.json').exists())

    def test_extraction_paths_cannot_escape_artifact_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'escapes storage'):
                exporter.within(Path(tmp), '../private-file')


if __name__ == '__main__':
    unittest.main()
