import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { validateEvidence, findPassages, loadEvidence, citationText } from './evidence-data.js';
import { renderReader, renderCompanyList, renderPassageList } from './evidence-render.js';

const read = path => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'));
const fixture = read('./evidence-preview.json');
const source = read('../research/evidence_v2/xiu_resolution_5_companies.json');
const clone = () => structuredClone(fixture);

test('portable fixture preserves all 35 original quotations, identities, weights and checks', () => {
  assert.equal(validateEvidence(fixture), fixture);
  assert.equal(fixture.passages.length, 35); assert.equal(fixture.documents.length, 5);
  assert.equal(fixture.scope.documented_holding_weight_pct, '19.71');
  for (const original of source.passages) {
    const p = fixture.passages.find(p => p.evidence_id === original.evidence_id);
    for (const key of Object.keys(original)) assert.deepEqual(p[key], original[key], key);
  }
  assert.equal(fixture.source_artifact.sha256, createHash('sha256').update(readFileSync(new URL('../research/evidence_v2/xiu_resolution_5_companies.json', import.meta.url))).digest('hex'));
  assert.doesNotMatch(JSON.stringify(fixture), /\/Users\/|local_file":|s3:\/\//);
});

test('wrong document hash, reassigned evidence, stale holdings and duplicated passages fail closed', () => {
  for (const mutate of [d => d.documents[0].sha256 = '0'.repeat(64),
    d => d.passages[0].subject_ticker = 'XIU.TO', d => d.passages[0].holding_weight_pct = 80,
    d => d.passages[0].context.holdings_as_of = '2025-11-12',
    d => d.passages.push(d.passages[0]), d => d.passages[0].stock_return_direction = 'positive']) {
    const d = clone(); mutate(d); assert.throws(() => validateEvidence(d));
  }
});

test('search stays within the original company; zero results remain empty', () => {
  assert.equal(findPassages(fixture, { ticker: 'RY.TO', query: '18,880' }).length, 1);
  assert.equal(findPassages(fixture, { ticker: 'XIU.TO' }).length, 0);
  assert.equal(findPassages(fixture, { ticker: 'CNR.TO', query: 'zzzzzzz' }).length, 0);
  assert.match(renderPassageList([], null), /No matching passages/);
});

test('CPKC provenance stays pending in the reader and copied citation', () => {
  const p = fixture.passages.find(p => p.subject_ticker === 'CP.TO');
  const d = fixture.documents.find(d => d.document_id === p.document_id);
  const h = fixture.holdings.find(h => h.ticker === p.subject_ticker);
  assert.match(renderReader(p, d, h), /Source provenance pending/);
  assert.match(renderReader(p, d, h), /Publication date/);
  assert.match(citationText(p, d), /pending_issuer_to_cdn_link/);
  assert.match(citationText(p, d), /Stock|stock-return prediction/);
  assert.ok(citationText(p, d).includes(p.excerpt_original));
});

test('table headings, units and footnotes accompany RBC data; original French quotes remain unchanged', () => {
  const p = fixture.passages.find(p => p.research_id === 'RBC-2025-02');
  const d = fixture.documents.find(d => d.document_id === p.document_id);
  const h = fixture.holdings.find(h => h.ticker === p.subject_ticker);
  const html = renderReader(p, d, h);
  assert.match(html, /Millions of Canadian dollars/); assert.match(html, /2025 undrawn/);
  assert.match(html, /Excludes securitization/);
  const atd = fixture.passages.find(p => p.subject_ticker === 'ATD.TO');
  assert.equal(atd.excerpt_original, source.passages.find(p => p.evidence_id === atd.evidence_id).excerpt_original);
});

test('untrusted metadata and unsafe source links cannot create executable HTML', () => {
  const p = { ...fixture.passages[0], excerpt_original: '<img src=x onerror=alert(1)>' };
  const d = { ...fixture.documents.find(d => d.document_id === p.document_id), source_url: 'javascript:alert(1)' };
  const h = fixture.holdings.find(h => h.ticker === p.subject_ticker);
  const html = renderReader(p, d, h);
  assert.doesNotMatch(html, /<img|href="javascript/); assert.match(html, /&lt;img/);
  assert.match(html, /Source link unavailable/);
  assert.match(renderCompanyList(fixture, 'CNR.TO'), /2.39%/);
});

test('local file errors do not fabricate evidence or fall back to the backend', async () => {
  let calls = 0;
  await assert.rejects(loadEvidence({ fetcher: async url => {
    calls++; assert.ok(url.pathname.endsWith('/evidence-preview.json'));
    return { ok: false, status: 404 };
  } }), /HTTP 404/);
  assert.equal(calls, 1);
  await assert.rejects(loadEvidence({ fetcher: async () => ({ ok: true, json: async () => ({}) }) }), /inconsistent/);
});
