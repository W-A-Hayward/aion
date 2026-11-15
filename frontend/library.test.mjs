import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { validateCatalog, loadCatalog, loadPayload, filterSources, searchDocuments, datasets, filterRows, documentPages } from './library-data.js';
import { sourceHeader, provenance, searchResults, dataTable } from './library-render.js';

const root = new URL('./', import.meta.url);
const read = path => JSON.parse(readFileSync(new URL(path, root)));
const catalog = read('library-catalog.json');
const rawPayload = a => read(a.payload.path).data;
const fetcher = async url => {
  const bytes = readFileSync(url);
  return { ok: true, arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) };
};
test('all 52 sources remain visible, including contextual, blocked and duplicate references', () => {
  assert.equal(validateCatalog(catalog), catalog);
  assert.equal(catalog.sources.length, 52); assert.ok(catalog.artifacts.length >= 64);
  assert.ok(catalog.artifacts.filter(a => a.payload).length >= 62);
  for (const [status, n] of Object.entries(catalog.summary.counts)) assert.equal(filterSources(catalog, { status }).length, n);
  assert.equal(filterSources(catalog, { query: 'SRC-052' })[0].duplicate_of, 'SRC-005');
  assert.equal(filterSources(catalog, { query: 'no-such-company-z' }).length, 0);
  assert.doesNotMatch(JSON.stringify(catalog), /\/Users\/|s3:\/\//);
});
test('every acquired extraction hash and source identity validates before display', async () => {
  for (const a of catalog.artifacts.filter(a => a.payload)) {
    const d = await loadPayload(a, { fetcher });
    assert.equal(d.kind, a.format);
    assert.equal(createHash('sha256').update(readFileSync(new URL(a.payload.path, root))).digest('hex'), a.payload.sha256);
  }
});
test('tampered bytes, source mismatch, traversal, missing files and missing extraction fail closed', async () => {
  const a = catalog.artifacts.find(a => a.payload);
  await assert.rejects(loadPayload({ ...a, payload: { ...a.payload, sha256: '0'.repeat(64) } }, { fetcher }), /integrity/);
  await assert.rejects(loadPayload({ ...a, sha256: '0'.repeat(64) }, { fetcher }), /identity/);
  await assert.rejects(loadPayload({ ...a, payload: { ...a.payload, path: '../outside.json' } }, { fetcher }), /Unsafe/);
  await assert.rejects(loadPayload(a, { fetcher: async () => ({ ok: false, status: 404 }) }), /HTTP 404/);
  await assert.rejects(loadPayload(catalog.artifacts.find(a => !a.payload), { fetcher }), /unavailable/);
  const c = structuredClone(catalog); c.sources[0].artifacts.push('0'.repeat(64)); assert.throws(() => validateCatalog(c));
  await assert.rejects(loadCatalog({ fetcher: async () => ({ ok: false, status: 404 }) }), /HTTP 404/);
});
test('XIU snapshots retain independent dates, rows and unnormalized weights; IVV missing values remain null', () => {
  const xi = catalog.sources[0].artifacts.map(h => catalog.artifacts.find(a => a.sha256 === h)).filter(a => a.format === 'holdings').map(rawPayload);
  assert.deepEqual(xi.map(d => d.as_of), ['2026-11-12', '2026-11-13']);
  assert.deepEqual(xi.map(d => d.total_displayed_weight_pct), ['100.02', '100.04']);
  assert.ok(xi.every(d => d.positions.length === 65 && d.weights_renormalized === false));
  const ds = datasets(xi[0])[0]; const cn = filterRows(ds, { query: 'CNR' });
  assert.equal(cn.length, 1); assert.equal(cn[0].weight_pct, '2.39');
  const ivv = rawPayload(catalog.artifacts.find(a => a.format === 'holdings' && a.source_ids.includes('SRC-004')));
  assert.equal(ivv.missing_weight_count, 4); assert.equal(ivv.total_displayed_weight_pct, null);
  assert.equal(datasets(ivv)[0].rows.length, 509);
});
test('BoC units/dates, all StatCan dimensions/statuses and SPY raw cells reach the browser unchanged', () => {
  const series = rawPayload(catalog.artifacts.find(a => a.format === 'time_series' && a.source_ids.includes('SRC-040')));
  const ds = datasets(series)[0]; assert.equal(ds.rows.length, 3736);
  const fx = filterRows(ds, { dimensions: { series_id: 'FXUSDCAD' }, from: '2026-11-01', to: '2026-11-13' });
  assert.ok(fx.length > 0 && fx.every(r => r.unit === 'CAD per USD' && r.date >= '2026-11-01' && r.date <= '2026-11-13'));
  const stat = datasets(rawPayload(catalog.artifacts.find(a => a.format === 'zip_csv')))[0];
  assert.equal(stat.rows.length, 46262); assert.ok(stat.columns.includes('STATUS') && stat.columns.includes('SCALAR_FACTOR'));
  assert.equal(stat.unit, 'Cents per litre');
  const canada = filterRows(stat, { dimensions: { GEO: 'Canada' }, from: '2026-09', to: '2026-09' });
  assert.ok(canada.length > 0 && canada.every(r => r.REF_DATE === '2026-09' && r.GEO === 'Canada'));
  const spy = datasets(rawPayload(catalog.artifacts.find(a => a.format === 'xlsx_cells')))[0];
  assert.equal(spy.unit, 'Not validated'); assert.ok(spy.rows.some(r => r.cell === 'B3' && r.value === 'As of 12-Nov-2026'));
  assert.equal(datasets(rawPayload(catalog.artifacts.find(a => a.format === 'json_metadata'))).length, 0);
});
test('local phrase search preserves source offsets and physical pages and excludes quarantine', async () => {
  const visited = [];
  const result = await searchDocuments(catalog, 'diesel', { loader: async a => { visited.push(a); return rawPayload(a); } });
  assert.ok(result.hits.length > 0); assert.ok(visited.every(a => !a.quarantine));
  assert.equal(result.excludedQuarantine, catalog.artifacts.filter(a => a.quarantine && ['pdf','html'].includes(a.format)).length); assert.equal(result.failures.length, 0);
  for (const h of result.hits) {
    const d = rawPayload(catalog.artifacts.find(a => a.sha256 === h.hash));
    const p = documentPages(d).find(p => p.page === h.page);
    assert.equal(p.text.slice(h.start, h.end), h.excerpt); assert.equal(h.citation_approved, false);
  }
  const failed = await searchDocuments(catalog, 'diesel', { sourceIds: ['SRC-001'], loader: async () => { throw new Error('missing file'); } });
  assert.equal(failed.hits.length, 0); assert.ok(failed.failures.length > 0);
  const abort = new AbortController(); abort.abort();
  await assert.rejects(searchDocuments(catalog, 'diesel', { signal: abort.signal, loader: async () => { throw new Error('should not read'); } }), /abort/i);
});

test('recovery metadata preserves the original 64 objects and all 35 reviewed passages without promotion', () => {
  const original = read('../research/source_pipeline/artifacts/runs/2026-11-15T153200689426+0000_2b6a5b/inventory.json');
  const oldHashes = new Set(original.sources.flatMap(s => s.artifacts.map(a => a.sha256).filter(Boolean)));
  assert.equal(oldHashes.size,64);
  for (const h of oldHashes) assert.ok(catalog.artifacts.some(a => a.sha256 === h));
  const recovered = catalog.sources.flatMap(s => s.recovery_candidates || []);
  assert.equal(recovered.length,21); assert.equal(new Set(recovered.map(r => r.id)).size,21);
  assert.equal(recovered.filter(r=>r.status === 'identity_reviewed_local').length,2);
  assert.equal(recovered.filter(r=>r.status === 'blocked_robots').length,14);
  assert.equal(recovered.filter(r=>r.status === 'supplied_identity_reviewed_provenance_pending').length,1);
  for (const r of recovered) assert.equal(r.citation_approved,false);
  for (const id of ['SRC-021','SRC-027']) {
    const s=catalog.sources.find(s=>s.id===id);assert.equal(s.usability,'context_only');
    const a=catalog.artifacts.find(a=>a.recovery_identity_review?.register_id===id);
    assert.equal(a.quarantine,false);assert.ok(a.publication_date);assert.equal(a.recovery_identity_review.stock_return_direction,'unknown');
    assert.match(sourceHeader(s,[a]),/financial claims unverified/);
  }
  assert.ok(catalog.artifacts.find(a=>a.source_ids.includes('SRC-026')&&a.format==='pdf').quarantine);
  assert.equal(read('evidence-preview.json').passages.length,35);
});

test('supplied methodology keeps provenance pending and separates edition from future effective dates', async () => {
  const a=catalog.artifacts.find(a=>a.sha256==='4113c09c0d9d24f1b396a1d4558b0b5d238fb14b9df454f3bd3cfd762fd2c150');
  assert.equal(a.quarantine,true);assert.equal(a.original_url,null);assert.equal(a.retrieved_at,null);
  assert.equal(a.publication_date,null);assert.equal(a.edition.year_month,'2026-11');
  assert.match(a.supplied_identity_review.temporal_limit,/2026-12-18/);
  assert.match(a.source_verification,/UNVERIFIED/);
  const d=await loadPayload(a,{fetcher});assert.equal(d.pages.length,42);
  assert.match(d.pages[15].text,/S&P\/TSX 60 Methodology/);
});
test('source text and links cannot inject HTML; provisional status remains explicit', () => {
  const malicious = '<img src=x onerror=alert(1)>';
  const s = { ...catalog.sources[0], title: malicious, url: 'javascript:alert(1)' };
  assert.doesNotMatch(sourceHeader(s, []), /<img|href="javascript/);
  const html = searchResults({ hits: [{ hash: '0'.repeat(64), sourceId: 'SRC-001', title: malicious, excerpt: malicious, page: 1 }], searched: 1, failures: [], excludedQuarantine: 1 });
  assert.match(html, /not an AI answer/); assert.doesNotMatch(html, /<img/);
  assert.match(provenance(catalog.artifacts[0]), /Not verified \/ unavailable/);
  assert.doesNotMatch(dataTable({ name: 'test', columns: ['v'] }, [{ v: malicious }], 0), /<img/);
});
