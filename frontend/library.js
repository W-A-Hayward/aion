import { loadCatalog, loadPayload, filterSources, documentPages, searchDocuments, datasets, filterRows } from './library-data.js';
import { sourceList, sourceHeader, provenance, options, searchResults, dataTable } from './library-render.js';
import { escapeHTML as e } from './formatters.js';

export function initLibrary(doc = document) {
  const root = doc.querySelector('#research-library');
  if (!root) return;
  const $ = s => root.querySelector(s);
  let catalog, selectedSource, artifact, extracted, pages = [], pageIndex = 0, sheets = [], sheetIndex = 0;
  let rowOffset = 0, resultOffset = 0, result, request, searchRequest, opening = 0;
  const clearFilters = () => { for (const id of ['rl-query', 'rl-group', 'rl-status-filter', 'rl-format']) $(`#${id}`).value = ''; };
  const visibleSources = () => filterSources(catalog, { query: $('#rl-query').value, group: $('#rl-group').value,
    status: $('#rl-status-filter').value, format: $('#rl-format').value });
  function list() {
    if (!catalog) return;
    const visible = visibleSources();
    $('#rl-list').innerHTML = sourceList(visible, selectedSource);
    $('#rl-count').textContent = `${visible.length} / ${catalog.sources.length} register entries`;
  }
  function reveal() {
    $('#rl-workspace').hidden = false;
    $('#rl-toggle').setAttribute('aria-expanded', 'true');
    root.scrollIntoView({ behavior: 'instant', block: 'start' });
    $('#rl-title').focus({ preventScroll: true });
  }
  async function load() {
    $('#rl-status').textContent = 'Loading the audited local source catalog…';
    $('#rl-retry').hidden = true; root.setAttribute('aria-busy', 'true');
    try {
      catalog = await loadCatalog({ fresh: true });
      const counts = catalog.sources.reduce((out, s) => { out[s.usability] = (out[s.usability] || 0) + 1; return out; }, {});
      $('#rl-summary').textContent = `${catalog.sources.length} sources · ${catalog.artifacts.length} unique files · ${catalog.artifacts.filter(a => a.payload).length} readable extractions`;
      $('#rl-status').textContent = `${counts.usable || 0} usable for intended research · ${counts.context_only || 0} context only · ${counts.needs_attention || 0} need attention. Catalog as of ${catalog.catalog_as_of}. Local acquisition, not live AWS data.`;
      if (catalog.recovery_summary) $('#rl-status').textContent += ` Recovery review: ${catalog.recovery_summary.candidates} candidates across ${catalog.recovery_summary.register_entries_covered} register entries. Open a source’s “Recovery links & validation” for actual results.`;
      $('#rl-group').innerHTML = '<option value="">All source groups</option>' + options([...new Set(catalog.sources.map(s => s.group))].sort());
      $('#rl-format').innerHTML = '<option value="">All file formats</option>' + options([...new Set(catalog.artifacts.map(a => a.format))].sort());
      list(); await selectSource(selectedSource || catalog.sources[0]?.id);
    } catch (err) {
      $('#rl-status').textContent = `Library unavailable. ${err.message} Serve frontend over local HTTP and build the local research bundle.`;
      $('#rl-retry').hidden = false;
    } finally { root.setAttribute('aria-busy', 'false'); }
  }
  async function selectSource(id, hash, page) {
    const s = catalog?.sources.find(s => s.id === id);
    if (!s) return;
    selectedSource = id; list();
    const files = s.artifacts.map(h => catalog.artifacts.find(a => a.sha256 === h));
    request?.abort(); artifact = null; extracted = null;
    $('#rl-detail').innerHTML = sourceHeader(s, files) + '<div id="rl-artifact" aria-live="polite"></div>';
    if (!files.length) return;
    const chosen = files.find(a => a.sha256 === hash) || files[0];
    $('#rl-file').value = chosen.sha256;
    await selectArtifact(chosen.sha256, page);
  }
  async function selectArtifact(hash, requestedPage, allowQuarantine = false) {
    request?.abort(); request = new AbortController(); const own = request;
    artifact = catalog.artifacts.find(a => a.sha256 === hash);
    extracted = null; pages = []; sheets = []; pageIndex = 0; sheetIndex = 0; rowOffset = 0;
    const a = artifact, container = $('#rl-artifact');
    container.innerHTML = provenance(a)
      + (a.supplied_identity_review ? `<p class="rl-caution">${e(a.supplied_identity_review.temporal_limit)}</p><p class="note">${e(a.supplied_identity_review.scope_limit)}</p>` : '')
      + '<div id="rl-content"></div>';
    if (a.quarantine && !allowQuarantine) {
      $('#rl-content').innerHTML = '<div class="rl-caution"><h4>Quarantined source</h4><p>Identity, reporting period or official provenance needs review. Excluded from document search and evidence answers.</p><button type="button" class="ghost-button" id="rl-review-quarantine">Inspect for manual review</button></div>';
      return;
    }
    $('#rl-content').textContent = 'Checking extraction integrity and opening the local file…';
    container.setAttribute('aria-busy', 'true');
    try {
      const loaded = await loadPayload(a, { signal: own.signal });
      if (own.signal.aborted) return;
      extracted = loaded;
      pages = documentPages(extracted); sheets = datasets(extracted);
      const warning = `<p class="rl-caution">${a.quarantine ? 'QUARANTINED · manual review only. ' : ''}Extracted source material · not an approved citation. Operational disclosures do not establish a stock-return direction or a Brent beta.</p><p class="note"><a href="./${e(a.payload.path)}" download="${e(a.sha256)}.json">Export complete extracted JSON</a> · preserves every source row and field.</p>`;
      if (pages.length) {
        pageIndex = Math.max(0, pages.findIndex(p => p.page === Number(requestedPage)));
        $('#rl-content').innerHTML = warning + '<div class="rl-pagination"><button type="button" id="rl-prev-page">← Previous</button><label>Source page<select id="rl-page"></select></label><button type="button" id="rl-next-page">Next →</button></div><p class="note" id="rl-page-note"></p><pre id="rl-page-text" class="rl-page-text" tabindex="0" aria-label="Extracted original source text"></pre>';
        $('#rl-page').innerHTML = pages.map((p, i) => `<option value="${i}">${p.page ? `PDF page ${p.page}` : 'Web text'}</option>`).join('');
        drawPage();
      } else if (sheets.length) {
        $('#rl-content').innerHTML = warning + `<label>Extracted table<select id="rl-sheet">${sheets.map((s, i) => `<option value="${i}">${e(s.name)}</option>`).join('')}</select></label><div id="rl-dataset"></div>`;
        drawDataset();
      } else {
        $('#rl-content').innerHTML = warning + '<h4>API metadata / navigation response</h4><p>This is not a table of financial observations.</p><pre class="rl-page-text" id="rl-metadata"></pre>';
        $('#rl-metadata').textContent = JSON.stringify(extracted, null, 2);
      }
    } catch (err) {
      if (!own.signal.aborted) $('#rl-content').innerHTML = `<p class="rl-caution">${e(err.message)} ${e(a.extraction_error || '')}</p><button type="button" id="rl-retry-file">Retry local extraction</button>`;
    } finally { if (!own.signal.aborted) container.setAttribute('aria-busy', 'false'); }
  }
  function drawPage() {
    $('#rl-page').value = String(pageIndex);
    $('#rl-page-text').textContent = pages[pageIndex].text || 'No extractable text on this page. Original visual review is required.';
    $('#rl-page-note').textContent = `${pageIndex + 1} / ${pages.length} extracted pages. ${pages[pageIndex].page ? 'Physical PDF page number; printed page not mapped. Layout and table relationships require original PDF verification.' : 'HTML text; no PDF or printed page reference.'}`;
    $('#rl-prev-page').disabled = pageIndex === 0; $('#rl-next-page').disabled = pageIndex === pages.length - 1;
  }
  function drawDataset() {
    rowOffset = 0; const ds = sheets[sheetIndex];
    $('#rl-dataset').innerHTML = `<p>${e(ds.details)}</p><div class="rl-data-filters"><label>Find a row<input type="search" id="rl-row-query" placeholder="Ticker, name, value…"></label>
      ${ds.dimensions.map(k => `<label>${e(k)}<select data-dimension="${e(k)}"><option value="">All</option>${options([...new Set(ds.rows.map(r => String(r[k] ?? '')))].filter(Boolean).sort())}</select></label>`).join('')}
      ${ds.dateField ? `<label>From <input id="rl-from" type="${ds.kind === 'statcan_table' ? 'month' : 'date'}"></label><label>To <input id="rl-to" type="${ds.kind === 'statcan_table' ? 'month' : 'date'}"></label>` : ''}</div>
      <p id="rl-row-count" role="status"></p><div id="rl-data-table"></div><div class="rl-pagination"><button id="rl-prev-rows" type="button">← Previous 50</button><span id="rl-row-range"></span><button id="rl-next-rows" type="button">Next 50 →</button></div>`;
    drawRows();
  }
  function drawRows() {
    const ds = sheets[sheetIndex];
    const rows = filterRows(ds, { query: $('#rl-row-query').value,
      dimensions: Object.fromEntries([...root.querySelectorAll('[data-dimension]')].map(el => [el.dataset.dimension, el.value])),
      from: $('#rl-from')?.value || '', to: $('#rl-to')?.value || '' });
    rowOffset = Math.min(rowOffset, Math.max(0, Math.floor((rows.length - 1) / 50) * 50));
    $('#rl-row-count').textContent = `${rows.length.toLocaleString('en-CA')} / ${ds.rows.length.toLocaleString('en-CA')} source rows. Units: ${ds.unit || 'not validated'}.`;
    $('#rl-data-table').innerHTML = rows.length ? dataTable(ds, rows, rowOffset) : '<p class="rl-empty">No matching observations. Missing observations are never replaced by zero.</p>';
    $('#rl-row-range').textContent = rows.length ? `${rowOffset + 1}–${Math.min(rowOffset + 50, rows.length)}` : '0';
    $('#rl-prev-rows').disabled = rowOffset === 0; $('#rl-next-rows').disabled = rowOffset + 50 >= rows.length;
  }
  function drawResults() {
    $('#rl-search-results').innerHTML = searchResults(result, resultOffset) + `<div class="rl-pagination"><button id="rl-prev-hits" type="button" ${resultOffset === 0 ? 'disabled' : ''}>← Previous</button><span>${result.hits.length ? resultOffset + 1 : 0}–${Math.min(resultOffset + 20, result.hits.length)}</span><button id="rl-next-hits" type="button" ${resultOffset + 20 >= result.hits.length ? 'disabled' : ''}>Next →</button></div>`;
  }
  async function search(event) {
    event.preventDefault(); if (!catalog) return;
    searchRequest?.abort(); searchRequest = new AbortController(); const own = searchRequest;
    $('#rl-stop-search').hidden = false; $('#rl-search-results').textContent = 'Searching local extracted pages…';
    $('#rl-search-results').setAttribute('aria-busy', 'true');
    try {
      result = await searchDocuments(catalog, $('#rl-text-query').value, { signal: own.signal,
        sourceIds: visibleSources().map(s => s.id), onProgress: (done, total) => { $('#rl-search-progress').textContent = `Read ${done} / ${total} documents…`; } });
      if (own.signal.aborted) return;
      resultOffset = 0; drawResults(); $('#rl-search-progress').textContent = 'Search complete. Results use the filters selected when the search began.';
    } catch (err) { if (!own.signal.aborted) $('#rl-search-results').textContent = err.message; }
    finally { if (searchRequest === own) { $('#rl-stop-search').hidden = true; $('#rl-search-results').setAttribute('aria-busy', 'false'); } }
  }
  async function openDetail(detail) {
    const token = ++opening;
    reveal(); if (!catalog) await load();
    if (!catalog || token !== opening) return;
    clearFilters();
    if (detail.ticker) $('#rl-query').value = detail.ticker;
    list();
    const a = catalog.artifacts.find(a => a.sha256 === detail.hash);
    const id = detail.sourceId || a?.source_ids[0] || visibleSources()[0]?.id;
    if (id) await selectSource(id, detail.hash, detail.page);
    if (token === opening && (detail.hash || detail.ticker)) { $('#rl-detail').focus({ preventScroll: true }); $('#rl-detail').scrollIntoView({ behavior: 'instant', block: 'start' }); }
  }
  root.addEventListener('click', event => {
    const b = event.target.closest('button'); if (!b) return;
    if (b.dataset.source) selectSource(b.dataset.source);
    if (b.id === 'rl-toggle') { if ($('#rl-workspace').hidden) reveal(); else { $('#rl-workspace').hidden = true; b.setAttribute('aria-expanded', 'false'); } }
    if (b.id === 'rl-retry') load();
    if (b.id === 'rl-clear') { clearFilters(); list(); }
    if (b.id === 'rl-review-quarantine') selectArtifact(artifact.sha256, null, true);
    if (b.id === 'rl-retry-file') selectArtifact(artifact.sha256);
    if (b.id === 'rl-prev-page') { pageIndex--; drawPage(); }
    if (b.id === 'rl-next-page') { pageIndex++; drawPage(); }
    if (b.id === 'rl-prev-rows') { rowOffset -= 50; drawRows(); }
    if (b.id === 'rl-next-rows') { rowOffset += 50; drawRows(); }
    if (b.id === 'rl-prev-hits') { resultOffset -= 20; drawResults(); }
    if (b.id === 'rl-next-hits') { resultOffset += 20; drawResults(); }
    if (b.id === 'rl-stop-search') { searchRequest?.abort(); $('#rl-search-results').textContent = 'Local search stopped.'; $('#rl-search-progress').textContent = ''; }
  });
  root.addEventListener('input', event => {
    if (event.target.id === 'rl-query') list();
    if (event.target.id === 'rl-row-query') { rowOffset = 0; drawRows(); }
  });
  root.addEventListener('change', event => {
    const el = event.target;
    if (['rl-group', 'rl-status-filter', 'rl-format'].includes(el.id)) list();
    if (el.id === 'rl-file') selectArtifact(el.value);
    if (el.id === 'rl-page') { pageIndex = Number(el.value); drawPage(); }
    if (el.id === 'rl-sheet') { sheetIndex = Number(el.value); drawDataset(); }
    if (el.hasAttribute('data-dimension') || ['rl-from', 'rl-to'].includes(el.id)) { rowOffset = 0; drawRows(); }
  });
  $('#rl-search-form').addEventListener('submit', search);
  doc.addEventListener('aion:open-library', event => openDetail(event.detail || {}));
  doc.addEventListener('click', event => {
    const hit = event.target.closest('[data-library-hit]');
    if (hit) openDetail({ hash: hit.dataset.libraryHit, sourceId: hit.dataset.sourceId, page: Number(hit.dataset.page) });
    if (event.target.closest('[data-open-library]')) openDetail({});
  });
  load();
}
if (typeof document !== 'undefined') initLibrary();
