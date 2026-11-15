// Local documentary adapter. Independent of the statistics API and its availability.
export function validateEvidence(data) {
  const fail = () => { throw new Error('The local evidence file has inconsistent identities or holdings.'); };
  if (data?.schema_version !== 1 || data.mode !== 'local_research' || data.investigation_ticker !== 'XIU.TO'
    || data.holdings_snapshot?.as_of !== '2026-11-12') fail();
  for (const key of ['holdings', 'documents', 'passages']) if (!Array.isArray(data[key])) fail();
  const docs = new Map(data.documents.map(d => [d.document_id, d]));
  const holdings = new Map(data.holdings.map(h => [h.ticker, h]));
  if (docs.size !== data.documents.length || holdings.size !== data.holdings.length) fail();
  for (const d of docs.values()) {
    if (!/^[a-f0-9]{64}$/.test(d.sha256) || d.document_id !== `doc:sha256:${d.sha256}`) fail();
  }
  for (const h of holdings.values()) if (!Number.isFinite(h.weight_pct) || h.weight_pct < 0 || h.weight_pct > 100) fail();
  const ids = new Set();
  for (const p of data.passages) {
    const d = docs.get(p.document_id), h = holdings.get(p.subject_ticker), c = p.context;
    if (!d || !h || ids.has(p.evidence_id) || p.ticker !== h.ticker || p.document_sha256 !== d.sha256
      || p.holding_weight_pct !== h.weight_pct || p.evidence_kind !== 'operational'
      || p.stock_return_direction !== 'unknown' || c?.association_type !== 'holding'
      || c.investigation_ticker !== data.investigation_ticker || c.subject_ticker !== h.ticker
      || c.holding_row_id !== h.row_id || c.holdings_as_of !== data.holdings_snapshot.as_of
      || c.holdings_source_id !== data.holdings_snapshot.source_id
      || typeof p.excerpt_original !== 'string' || !p.excerpt_original.trim()
      || !Number.isInteger(p.pdf_page) || p.pdf_page < 1) fail();
    ids.add(p.evidence_id);
  }
  if (data.scope?.passage_count !== data.passages.length || data.scope.document_count !== docs.size) fail();
  return data;
}

export async function loadEvidence({ fetcher = globalThis.fetch, signal } = {}) {
  const response = await fetcher(new URL('./evidence-preview.json', import.meta.url),
    { signal, credentials: 'same-origin', headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error(`Local research could not be loaded (HTTP ${response.status}).`);
  return validateEvidence(await response.json());
}

export function findPassages(data, { ticker, query = '' }) {
  const needle = query.trim().toLocaleLowerCase();
  return data.passages.filter(p => p.subject_ticker === ticker && (!needle ||
    [p.excerpt_original, p.section, p.research_id, p.operational_channel].join(' ').toLocaleLowerCase().includes(needle)));
}

export function citationText(passage, doc) {
  return `${doc.issuer}. ${doc.document_title}. Fiscal year ended ${doc.fiscal_year_end || 'not supplied'}.
PDF page ${passage.pdf_page}; printed page ${passage.printed_page || 'not supplied'}; ${passage.section}.
${passage.research_id} · ${passage.subject_ticker}

“${passage.excerpt_original}”

Source: ${doc.source_url || 'unavailable'}
SHA-256: ${doc.sha256}
Quote status (recorded research check, not rerun here): ${passage.verification?.quote_pdf_text_check?.status || passage.quote_verification?.status || 'unverified'}
Source provenance: ${doc.provenance_status || doc.source_verification?.status || 'unverified'}
Current link availability: not checked. Research candidate; operational evidence, not a Brent beta or a stock-return prediction.`;
}
