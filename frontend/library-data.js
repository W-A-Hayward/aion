// Read-only local research adapter. Deliberately independent of statistical/API tables.
const base = new URL('./', import.meta.url);
const hashPattern = /^[a-f0-9]{64}$/;
export const DOCUMENT_FORMATS = new Set(['pdf', 'html']);
const payloadCache = new Map();
let catalogCache;

export function validateCatalog(c) {
  const fail = () => { throw new Error('Local research catalog is inconsistent. Rebuild the audited bundle.'); };
  if (c?.schema_version !== 1 || c.mode !== 'local_acquired_research' || !hashPattern.test(c.inventory_sha256)
      || !Array.isArray(c.sources) || !Array.isArray(c.artifacts)) fail();
  const ids = new Set(), hashes = new Set();
  for (const a of c.artifacts) {
    if (!hashPattern.test(a.sha256) || hashes.has(a.sha256) || typeof a.quarantine !== 'boolean' || a.citation_approved !== false) fail();
    hashes.add(a.sha256);
    if (a.payload && (a.payload.path !== `research-data/${c.inventory_sha256}/${a.sha256}.json`
        || !hashPattern.test(a.payload.sha256) || !(a.payload.bytes > 0))) fail();
  }
  for (const s of c.sources) {
    if (!/^SRC-\d{3}$/.test(s.id) || ids.has(s.id) || !Array.isArray(s.artifacts)
        || s.artifacts.some(h => !hashes.has(h)) || !['usable', 'context_only', 'needs_attention'].includes(s.usability)) fail();
    ids.add(s.id);
  }
  if (c.artifacts.some(a => !a.source_ids?.length || a.source_ids.some(id => !ids.has(id)
      || !c.sources.find(s => s.id === id).artifacts.includes(a.sha256)))) fail();
  return c;
}

export async function loadCatalog({ fetcher = fetch, signal, fresh = false } = {}) {
  if (catalogCache && !fresh && fetcher === globalThis.fetch) return catalogCache;
  const r = await fetcher(new URL('library-catalog.json', base), { signal, cache: 'no-store' });
  if (!r.ok) throw new Error(`Catalog unavailable (HTTP ${r.status}).`);
  const c = validateCatalog(await r.json());
  if (fetcher === globalThis.fetch) catalogCache = c;
  return c;
}

export async function loadPayload(a, { fetcher = fetch, signal } = {}) {
  if (!a.payload) throw new Error('Text or structured extraction is unavailable for this file.');
  if (!/^research-data\/[a-f0-9]{64}\/[a-f0-9]{64}\.json$/.test(a.payload.path)) throw new Error('Unsafe payload path.');
  signal?.throwIfAborted();
  if (fetcher === globalThis.fetch && payloadCache.has(a.payload.sha256)) return payloadCache.get(a.payload.sha256);
  const r = await fetcher(new URL(a.payload.path, base), { signal });
  if (!r.ok) throw new Error(`Local extraction unavailable (HTTP ${r.status}).`);
  const bytes = await r.arrayBuffer();
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), b => b.toString(16).padStart(2, '0')).join('');
  if (bytes.byteLength !== a.payload.bytes || digest !== a.payload.sha256) throw new Error('Extraction integrity check failed. Nothing has been displayed.');
  const p = JSON.parse(new TextDecoder().decode(bytes));
  if (p.schema_version !== 1 || p.artifact_sha256 !== a.sha256 || p.format !== a.format || p.data?.kind !== a.format) throw new Error('Source identity mismatch.');
  signal?.throwIfAborted();
  if (fetcher === globalThis.fetch) payloadCache.set(a.payload.sha256, p.data);
  return p.data;
}

export function filterSources(c, { query = '', group = '', status = '', format = '' } = {}) {
  const q = query.trim().toLowerCase();
  return c.sources.filter(s => (!group || s.group === group) && (!status || s.usability === status)
    && (!format || s.artifacts.some(h => c.artifacts.find(a => a.sha256 === h)?.format === format))
    && (!q || [s.id, s.title, s.publisher, s.subjects, s.purpose].join(' ').toLowerCase().includes(q)));
}

export function documentPages(d) {
  return d.kind === 'pdf' ? d.pages.map(p => ({ page: p.pdf_page, text: p.text }))
    : d.kind === 'html' ? [{ page: null, text: d.text || '' }] : [];
}

// An exact, case-insensitive phrase search; no generated answers or inferred financial claims.
export async function searchDocuments(c, query, { signal, sourceIds, loader = loadPayload, onProgress } = {}) {
  const phrase = query.trim().toLowerCase();
  if (phrase.length < 2) throw new Error('Enter at least two characters, for example “fuel surcharge”.');
  const candidates = c.artifacts.filter(a => !a.quarantine && a.payload && DOCUMENT_FORMATS.has(a.format)
    && (!sourceIds || a.source_ids.some(id => sourceIds.includes(id))));
  const hits = [], failures = []; let done = 0, cursor = 0;
  await Promise.all(Array.from({ length: Math.min(4, candidates.length) }, async () => {
    while (cursor < candidates.length) {
      signal?.throwIfAborted(); const a = candidates[cursor++];
      try {
        const d = await loader(a, { signal });
        for (const p of documentPages(d)) {
          const offset = p.text.toLowerCase().indexOf(phrase);
          if (offset < 0) continue;
          const start = Math.max(0, offset - 100), end = Math.min(p.text.length, offset + phrase.length + 180);
          hits.push({ hash: a.sha256, sourceId: a.source_ids[0], title: a.title, page: p.page,
            excerpt: p.text.slice(start, end), start, end, citation_approved: false });
        }
      } catch (error) {
        if (signal?.aborted) throw error;
        failures.push({ hash: a.sha256, message: error.message });
      }
      onProgress?.(++done, candidates.length);
    }
  }));
  signal?.throwIfAborted();
  hits.sort((a, b) => a.sourceId.localeCompare(b.sourceId) || a.hash.localeCompare(b.hash) || (a.page || 0) - (b.page || 0));
  return { hits, failures, searched: candidates.length, excludedQuarantine: c.artifacts.filter(a => a.quarantine && DOCUMENT_FORMATS.has(a.format)).length };
}

// All source rows remain available. Never renormalize holdings or fill missing values.
export function datasets(d) {
  if (d.kind === 'holdings') return [{ name: `Holdings as of ${d.as_of || 'unknown date'}`, kind: d.kind,
    columns: ['as_of', 'ticker_original', 'name', 'sector', 'asset_class', 'weight_pct', 'currency'],
    rows: d.positions, unit: d.unit, details: `Displayed total: ${d.total_displayed_weight_pct ?? 'unavailable'}%. Known weights: ${d.sum_known_weight_pct ?? d.total_displayed_weight_pct ?? 'unknown'}%. Missing weights: ${d.missing_weight_count ?? 'unknown'}. No normalization.`, dimensions: ['sector', 'asset_class'] }];
  if (d.kind === 'time_series') return [{ name: 'Dated observations', kind: d.kind,
    columns: ['date', 'series_id', 'value', 'unit', 'frequency', 'label'], rows: d.records,
    unit: (d.units || []).join(' / '), dimensions: ['series_id'], dateField: 'date', details: 'Original observations. Missing values stay missing; units are not combined.' }];
  if (d.kind === 'statcan_table') return [{ name: 'Statistics Canada observations', kind: d.kind,
    columns: d.source_columns, rows: d.records, unit: (d.units || []).join(' / '),
    dimensions: ['GEO', 'Type of fuel'], dateField: 'REF_DATE', details: `Scalar factors: ${(d.scalar_factors || []).join(', ')}. Consult STATUS, SYMBOL and footnotes before using any value.` }];
  if (d.kind === 'zip_csv') return d.members.flatMap(m => datasets(m.data).map(s => ({ ...s, name: m.member })));
  if (d.kind === 'xlsx_cells') return d.sheets.map(s => ({ name: s.sheet, kind: d.kind,
    columns: ['cell', 'value', 'type', 'style'], rows: s.rows.flat(), dimensions: [], unit: 'Not validated',
    details: 'Raw workbook cells. Holdings date, sector and weight mapping need validation before model use.' }));
  return [];
}

export function filterRows(ds, { query = '', dimensions = {}, from = '', to = '' } = {}) {
  const q = query.trim().toLowerCase();
  return ds.rows.filter(r => Object.entries(dimensions).every(([k, v]) => !v || String(r[k]) === v)
    && (!from || (r[ds.dateField] && r[ds.dateField] >= from)) && (!to || (r[ds.dateField] && r[ds.dateField] <= to))
    && (!q || ds.columns.some(k => String(r[k] ?? '').toLowerCase().includes(q))));
}
