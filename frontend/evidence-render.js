import { escapeHTML as esc, sourceURL } from './formatters.js';

export const COMPANIES = Object.freeze({
  'RY.TO': { name: 'Royal Bank of Canada', short: 'RBC', lens: 'Lending & credit risk' },
  'CNQ.TO': { name: 'Canadian Natural', short: 'CNQ', lens: 'Selling prices & differentials' },
  'CP.TO': { name: 'Canadian Pacific Kansas City', short: 'CPKC', lens: 'Diesel, surcharges & freight' },
  'CNR.TO': { name: 'Canadian National', short: 'CN', lens: 'Freight & residual fuel risk' },
  'ATD.TO': { name: 'Alimentation Couche-Tard', short: 'ATD', lens: 'Fuel sales & margins' },
});
const LABELS = {
  oil_related_cargo: 'What the railway carries', fuel_surcharge_lag: 'Recovery takes time',
  residual_diesel_exposure: 'What surcharges do not cover', oil_industry_demand: 'Demand from energy customers',
  petroleum_chemicals_revenue: 'Revenue table · context incomplete', fuel_cost: 'Fuel as an operating cost',
  diesel_price_risk: 'Diesel price risk', fuel_prices_margins: 'Fuel prices and margins',
  fuel_materiality: 'Fuel’s place in the business', oil_geopolitics: 'Oil and geopolitical risks',
  fuel_price_demand: 'Fuel volumes and demand', fuel_card_costs: 'Payment costs on fuel sales',
  credit_concentration_policy: 'How RBC defines concentration risk', oil_gas_credit_exposure: 'Oil-and-gas credit exposure',
  oil_gas_credit_quality: 'Oil-and-gas credit quality', ecl_commodity_price_input: 'Commodity prices in credit models',
  ecl_scenario_design: 'How credit scenarios change', realized_price_benchmark_linkage: 'How benchmarks reach selling prices',
  earnings_volatility_drivers: 'Drivers of earnings volatility', benchmark_price_linkage: 'WTI, Brent and currency',
  benchmark_prices_and_differentials: 'Benchmarks and regional differentials', wcs_differential: 'The WCS–WTI differential',
  realized_price: 'What the producer actually receives', price_sensitivity: 'A company cash-flow sensitivity',
  hedging_policy: 'The role of hedging', fuel_surcharge_pass_through: 'How fuel surcharges work',
  fuel_surcharge_materiality: 'The scale of fuel surcharges', fuel_surcharge_limits: 'Limits to cost recovery',
  fuel_price_net_impact: 'The reported net operating impact', energy_freight_mix: 'Energy-related freight',
};
export const passageTitle = p => LABELS[p.operational_channel] || String(p.operational_channel).replaceAll('_', ' ');
export const pendingSource = d => String(d.provenance_status || '').startsWith('pending_');
const pct = n => Number(n).toFixed(2);

export function renderCompanyList(data, ticker) {
  return [...data.holdings].sort((a, b) => b.weight_pct - a.weight_pct).map(h => {
    const meta = COMPANIES[h.ticker] || { name: h.company_name, short: h.ticker, lens: h.sector };
    const count = data.passages.filter(p => p.subject_ticker === h.ticker).length;
    return `<button type="button" class="ed-company" data-company="${esc(h.ticker)}" aria-pressed="${h.ticker === ticker}">
      <span class="ed-company-top"><b>${esc(meta.short)}</b><span>${pct(h.weight_pct)}% <small>of XIU</small></span></span>
      <span class="ed-company-name">${esc(meta.name)}</span><span class="ed-lens">${esc(meta.lens)}</span>
      <span class="ed-company-bottom">${esc(h.sector)} <span>${count} passages ↗</span></span>
    </button>`;
  }).join('');
}

export function renderPassageList(passages, selected) {
  if (!passages.length) return '<div class="ed-empty"><h3>No matching passages</h3><p>Try a shorter term or another company. This search covers this company’s local research only.</p><button type="button" class="ghost-button" data-clear-search>Clear search</button></div>';
  return passages.map((p, i) => `<button type="button" class="ed-passage" data-passage="${esc(p.evidence_id)}" aria-pressed="${p.evidence_id === selected}">
    <span class="ed-passage-no">${String(i + 1).padStart(2, '0')}</span><span><strong>${esc(passageTitle(p))}</strong>
    <small>${esc(p.research_id)} · PDF p. ${p.pdf_page}</small></span><span aria-hidden="true">↗</span></button>`).join('');
}

function tableContext(table) {
  if (!table) return '';
  const entries = Object.entries(table).filter(([key]) => !['columns', 'values', 'footnotes', 'title'].includes(key));
  let values = '';
  // A legible transcription of the supplied mapping, never recalculated numbers.
  if (Array.isArray(table.columns) && Array.isArray(table.values)) {
    values = `<table><caption class="sr-only">${esc(table.title)}</caption><thead><tr><th scope="col">Reported measure</th><th scope="col">Value</th></tr></thead><tbody>${table.columns.map((col, i) => `<tr><th scope="row">${esc(col)}</th><td>${esc(table.values[i] ?? 'Not supplied')}</td></tr>`).join('')}</tbody></table>`;
  } else if (Array.isArray(table.columns) && table.values && typeof table.values === 'object') {
    values = `<table><caption class="sr-only">${esc(table.title)}</caption><thead><tr><th scope="col">Benchmark</th>${table.columns.map(c => `<th scope="col">${esc(c)}</th>`).join('')}</tr></thead><tbody>${Object.entries(table.values).map(([name, row]) => `<tr><th scope="row">${esc(name)}</th>${table.columns.map((_, i) => `<td>${esc(row[i] ?? 'Not supplied')}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  }
  return `<div class="ed-table-context"><b>${esc(table.title || 'Table context')}</b><dl>${entries.map(([key, value]) =>
    `<div><dt>${esc(key.replaceAll('_', ' '))}</dt><dd>${esc(typeof value === 'string' ? value : JSON.stringify(value))}</dd></div>`).join('')}</dl>${values}
    ${table.footnotes?.length ? `<b>Footnotes & research review notes</b><ul>${table.footnotes.map(f => `<li>${esc(f)}</li>`).join('')}</ul>` : '<p>No additional footnotes supplied in this research mapping.</p>'}</div>`;
}

export function renderReader(p, doc, holding, { expert = false } = {}) {
  if (!p) return '<div class="ed-empty"><h3>Choose a passage</h3><p>The original quotation, page and verification record will appear here.</p></div>';
  const check = p.verification?.quote_pdf_text_check;
  const quoteStatus = check?.status === 'verified' ? 'PDF text checked in research' : 'Check reported by research register';
  const url = sourceURL(doc.source_url);
  const pageURL = url ? new URL(url) : null;
  if (pageURL) pageURL.hash = `page=${p.pdf_page}`;
  const pending = pendingSource(doc);
  const ctx = p.reading_context;
  const contextMissing = !ctx;
  const provenance = pending ? 'Pending · issuer-to-CDN link not established' :
    doc.source_verification?.status === 'reported_verified' ? 'Reported by acquisition receipt · not rechecked' :
      'Not independently verified · acquisition record retained';
  return `<div class="ed-reader-top"><span class="ed-eyebrow">03 / Read the source</span><span class="ed-page-number">PDF ${p.pdf_page} <span>/ printed ${esc(p.printed_page || 'unavailable')}</span></span></div>
    <div class="ed-reader-body">
      <p class="ed-document-kind">${esc(doc.language.toUpperCase())} · ANNUAL REPORT · FY ${esc(doc.fiscal_year)}</p>
      <h3>${esc(doc.document_title)}</h3><p class="ed-issuer">${esc(doc.issuer)}</p>
      ${pending ? '<p class="ed-warning"><b>Source provenance pending.</b> The PDF’s contents were examined, but its link from the issuer’s website to the CDN has not been established.</p>' : ''}
      <p class="ed-section-label">${esc(p.section)}</p>
      <div class="ed-quote"><span class="ed-quote-label">Original quotation · ${esc(p.research_id)}</span><span class="ed-quote-check">${esc(quoteStatus)}</span><blockquote lang="${esc(doc.language)}">${esc(p.excerpt_original)}</blockquote></div>
      ${tableContext(ctx?.table)}
      ${ctx?.unit_basis ? `<p class="ed-warning"><b>Units and currency.</b> ${esc(ctx.unit_basis)}</p>` : ''}
      ${contextMissing ? '<p class="ed-warning">Full surrounding text and table footnotes are not included in this research record. Check the original page before using numerical claims. A heading alone is not a financial finding.</p>' : ''}
      <div class="ed-reading-rule"><span class="ed-eyebrow">What this tells you</span><p>This is a disclosure about <b>${esc(COMPANIES[p.subject_ticker]?.short || p.subject_ticker)}</b>’s business. Its ${pct(holding.weight_pct)}% XIU weight is portfolio composition. This passage does not measure its contribution to XIU’s oil beta or predict its share price.</p></div>
      ${ctx ? `<details class="ed-details" ${expert ? 'open' : ''}><summary>Surrounding text & research interpretation</summary>
        <h4>Before the quotation · research context</h4><p class="ed-context">${esc(ctx.context_before || 'Not supplied')}</p>
        <h4>After the quotation · research context</h4><p class="ed-context">${esc(ctx.context_after || 'Not supplied')}</p>
        <h4>Researcher interpretation · not issuer text</h4><p>${esc(p.interpretation || 'Not supplied')}</p></details>` : ''}
      <details class="ed-details" ${expert ? 'open' : ''}><summary>Verification & document identity</summary>
        <dl class="ed-verification"><div><dt>Quotation</dt><dd>${esc(quoteStatus)}</dd></div>
          <div><dt>Match method</dt><dd>${esc(check?.match_method || 'Reported only; not re-extracted here')}</dd></div>
          <div><dt>Official provenance</dt><dd>${esc(provenance)}</dd></div>
          <div><dt>Issuer identity</dt><dd>${esc(doc.issuer_verification?.status || 'unverified')}</dd></div>
          <div><dt>PDF bytes</dt><dd>${esc(doc.local_file_verification?.status || 'unverified')} · recorded local hash comparison</dd></div>
          <div><dt>Financial period ends</dt><dd>${esc(doc.fiscal_year_end || 'Unavailable')}</dd></div>
          <div><dt>Publication date</dt><dd>${esc(doc.publication_date || 'Unavailable · not inferred from fiscal year')}</dd></div>
          <div><dt>URL availability now</dt><dd>Not checked</dd></div>
          <div><dt>Holding membership</dt><dd>${esc(p.subject_ticker)} · original ticker ${esc(p.holding_ticker_original)} · 12 Nov 2026 snapshot</dd></div>
          <div><dt>Stock-return direction</dt><dd>Unknown</dd></div>
          <div><dt>SHA-256</dt><dd><code>${esc(doc.sha256)}</code></dd></div>
          <div><dt>Evidence ID</dt><dd><code>${esc(p.evidence_id)}</code></dd></div>
        </dl></details>
      <div class="ed-source-actions">${pageURL ? `<a href="${esc(pageURL.href)}" target="_blank" rel="noopener noreferrer" class="ed-primary">Open source · PDF p. ${p.pdf_page} ↗</a>` : '<span class="ed-warning">Source link unavailable</span>'}
        <button type="button" class="ghost-button" data-copy-citation>Copy citation</button></div>
      <p class="ed-source-disclaimer">External source; link availability is unverified. The PDF viewer may not honour the page link. No external document loads until you choose to open it.</p>
    </div>`;
}
