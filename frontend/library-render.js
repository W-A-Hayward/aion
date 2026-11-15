import { escapeHTML as e, sourceURL } from './formatters.js';
export const readable = value => value == null || value === '' ? 'Not verified / unavailable' : typeof value === 'object' ? JSON.stringify(value) : String(value);
export const badge = value => `<span class="rl-badge">${e(String(value).replaceAll('_', ' '))}</span>`;
export function link(url, label = 'Open original source ↗') {
  const safe = sourceURL(url);
  return safe ? `<a href="${e(safe)}" target="_blank" rel="noopener noreferrer">${e(label)}</a>` : '<span>Source link unavailable</span>';
}
export const options = (values, selected = '') => values.map(v => `<option value="${e(v)}"${v === selected ? ' selected' : ''}>${e(v)}</option>`).join('');
export function recoveryPanel(candidates = []) {
  if (!candidates.length) return '';
  const labels = {
    blocked_robots: 'Automated acquisition blocked by access-policy check',
    blocked_http: 'Access denied or rate-limited', unavailable_http: 'URL returned unavailable',
    pending_network: 'Network verification incomplete', pending_offline: 'Not checked online',
    pending_redirect_host: 'Redirect destination needs review', blocked_unsafe_redirect: 'Unsafe redirect stopped',
    acquired_manual_review_required: 'File acquired — identity/content review required',
    structured_validated_local: 'Local dataset structure validated — not model integration',
    identity_reviewed_local: 'Document identity reviewed locally — financial claims unverified',
    supplied_identity_reviewed_provenance_pending: 'Supplied PDF identity reviewed — official provenance pending',
    related_reference_no_duplicate_download: 'Related reference — no duplicate download',
    reference_only_not_fetched: 'Optional guidance — not fetched', deferred_backend_work: 'Deferred API work',
  };
  return `<section class="rl-recovery" aria-label="Recovery source validation"><h4>Recovery links & validation</h4>
    <p class="note">Imported recovery suggestions are not verified citations. The original register, acquired files and quarantine decisions are preserved.</p>
    ${candidates.map(r => `<details><summary>${e(r.id)} · ${e(labels[r.status] || r.status)}</summary>
      <p><strong>${e(r.name_claim)}</strong></p><p>Requested period (unverified): ${e(r.period_claim)}<br>Checked: ${e(r.checked_at)}${r.http_status ? `<br>HTTP status: ${e(r.http_status)}` : ''}</p>
      ${r.reason ? `<p class="rl-caution">${e(r.reason === 'robots_unavailable_manual_review' ? 'The collector could not verify the site’s robots policy. This does not establish whether the document is available to a person using a browser.' : r.reason)}</p>` : ''}
      <p>${link(r.url, 'Candidate URL ↗')}${r.publisher_page ? ` · ${link(r.publisher_page, 'Claimed publisher page ↗')}` : ''}</p>
      ${r.related_source ? `<p>Related register entry: ${e(r.related_source)}. Not an additional independent publication.</p>` : ''}
      ${r.supplied_note_UNVERIFIED ? `<p>Supplied research note — UNVERIFIED: ${e(r.supplied_note_UNVERIFIED)}</p>` : ''}
      ${r.validation ? `<p>Validation results: ${e(readable(r.validation))}</p>` : '<p>No acquired bytes validated in this attempt.</p>'}
      ${r.sha256 ? `<p>Source SHA-256: ${e(r.sha256)}</p>` : ''}
      ${r.publisher_link_check ? `<p>Publisher-link check: ${e(readable(r.publisher_link_check))}</p>` : ''}
      ${r.identity_review ? `<p>Identity review: ${e(readable(r.identity_review))}</p>` : ''}
      ${r.existing_CDN_PDF_quarantine ? `<p class="rl-caution">CPKC: ${e(r.existing_CDN_PDF_quarantine)}</p>` : ''}
      ${r.previous_checks?.length ? `<details><summary>Previous checks retained (${r.previous_checks.length})</summary><pre class="rl-page-text">${e(readable(r.previous_checks))}</pre></details>` : ''}
      </details>`).join('')}</section>`;
}
export function sourceList(sources, selected) {
  return sources.length ? sources.map(s => `<button type="button" class="rl-source" data-source="${e(s.id)}" aria-pressed="${s.id === selected}">
    <span>${e(s.id)} · ${e(s.publisher)}</span><strong>${e(s.title)}</strong><small>${e(s.subjects)} · ${e(s.usability.replaceAll('_', ' '))} · ${s.artifacts.length} files</small></button>`).join('')
    : '<p class="rl-empty">No matching register entries. Clear the filters to see all sources.</p>';
}
export function sourceHeader(s, artifacts) {
  return `<header class="rl-source-header"><span class="ed-eyebrow">${e(s.id)} / ${e(s.group)}</span><h3>${e(s.title)}</h3>
    <p>${e(s.purpose)}</p>${badge(s.usability)} <span>${e(s.publisher)} · research targets: ${e(s.subjects || 'unspecified')}</span>
    <p class="note">Register targets do not establish ETF membership. Requested period: ${e(s.requested_period)}.</p>
    ${link(s.url)}${s.duplicate_of ? `<p>Duplicate register URL: ${e(s.duplicate_of)}.</p>` : ''}
    ${s.attention?.length ? `<p class="rl-caution">${e(s.attention.join(' · '))}</p>` : ''}
    <details><summary>Retrieval attempts and availability</summary><ul>${s.attempts.map(a => `<li>${e(a.status)}${a.reason ? ` — ${e(a.reason)}` : ''}${a.error ? ` — ${e(a.error)}` : ''} ${link(a.url, 'Attempt URL ↗')}</li>`).join('') || '<li>No retrieval receipt.</li>'}</ul></details>
    ${recoveryPanel(s.recovery_candidates)}
    ${artifacts.length ? `<label class="rl-file-label">Available local files<select id="rl-file">${artifacts.map(a => `<option value="${e(a.sha256)}">${e(a.format.toUpperCase())} · ${e(a.date_range?.min || a.reporting_period || '')} · ${e(a.file_label)}${a.quarantine ? ' · QUARANTINED' : ''}</option>`).join('')}</select></label>`
    : '<p class="rl-empty">No local file supplied. This register entry is a research reference, not available evidence.</p>'}</header>`;
}
export function provenance(a) {
  const fields = [ ['Issuer / publisher recorded', a.publisher], ['Reporting period', a.reporting_period], ['Fiscal year end', a.fiscal_year_end],
    ['Publication date', a.publication_date], ['Retrieved at', a.retrieved_at], ['Data dates', a.date_range],
    ['Official provenance', a.source_verification], ['Content verification', a.content_verification], ['Period check', a.period_check],
    ['Extraction', a.extraction_status], ['Source SHA-256', a.sha256], ['Byte integrity', a.source_byte_check],
    ['Observed title text', a.title_excerpt], ['Issuer text check', a.issuer_text_check],
    ['Verification scope', a.content_verification_scope], ['Current source-link status', a.current_link_status],
    ['Last recorded check', a.checked_at], ['Structured-data verification', a.structure_verification],
    ['Prior acquisition review', a.prior_review], ['Original retrieval status', a.original_retrieval_status],
    ['Recovery validation', a.recovery_validation], ['Publisher-link check', a.publisher_link_check],
    ['Local identity review (not financial claims)', a.recovery_identity_review],
    ['Document edition (not effective date)', a.edition], ['Supplied-file review', a.supplied_identity_review] ];
  return `<details class="rl-provenance"><summary>Source identity, dates and verification</summary><dl>${fields.map(([k, v]) => `<dt>${e(k)}</dt><dd>${e(readable(v))}</dd>`).join('')}</dl>
    <p>${link(a.original_url, 'Original URL ↗')} · ${link(a.final_url, 'Final URL ↗')}</p>
    ${a.publication_date_candidates?.length ? `<p>Unverified publication-date candidates: ${e(readable(a.publication_date_candidates))}</p>` : ''}
    <p>A matching hash identifies bytes. It does not verify a financial claim, official provenance or the report’s period.</p></details>`;
}
export function searchResults(result, offset = 0, limit = 20) {
  return `<p class="rl-results-note">${result.hits.length} matching pages / web texts across ${result.searched} files. ${result.excludedQuarantine} quarantined documents excluded. ${result.failures.length} files could not be searched.</p>
    ${result.failures.length ? `<details><summary>Incomplete search — file errors</summary>${result.failures.map(f => `<p>${e(f.hash)}: ${e(f.message)}</p>`).join('')}</details>` : ''}
    <p class="note">Exact phrase matches in extracted text, not an AI answer or approved citations. Open the whole page to check headings, units and footnotes.</p>
    ${result.hits.slice(offset, offset + limit).map(h => `<button type="button" class="rl-hit" data-library-hit="${e(h.hash)}" data-source-id="${e(h.sourceId)}" data-page="${h.page ?? ''}"><strong>${e(h.sourceId)} · ${e(h.title)}</strong><span>${h.page ? `PDF page ${h.page} · printed page not mapped` : 'Web text · no PDF page'}</span><q>${e(h.excerpt)}</q><small>Open source context →</small></button>`).join('') || '<p class="rl-empty">No exact match. Try “diesel”, “oil and gas” or “fuel surcharge”. No missing evidence has been inferred.</p>'}`;
}
export function dataTable(ds, rows, offset) {
  return `<div class="rl-table-scroll" tabindex="0" role="region" aria-label="Source data table"><table><caption>${e(ds.name)} · ${e(ds.unit || 'Units not validated')}</caption><thead><tr>${ds.columns.map(c => `<th scope="col">${e(c)}</th>`).join('')}</tr></thead><tbody>${rows.slice(offset, offset + 50).map(r => `<tr>${ds.columns.map(c => `<td>${r[c] == null || r[c] === '' ? '<span class="rl-missing">Missing</span>' : e(readable(r[c]))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}
