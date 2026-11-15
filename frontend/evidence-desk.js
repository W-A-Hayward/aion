import { loadEvidence, findPassages, citationText } from './evidence-data.js';
import { renderCompanyList, renderPassageList, renderReader, COMPANIES } from './evidence-render.js';

export function initEvidenceDesk(doc = document) {
  const root = doc.querySelector('#evidence-desk');
  if (!root) return;
  const $ = s => root.querySelector(s);
  let data, ticker = 'CNR.TO', selected, controller;
  const search = $('#ed-search');
  const status = $('#ed-status');
  const current = () => data?.passages.find(p => p.evidence_id === selected);
  const focusReader = () => {
    const reader = $('#ed-reader');
    reader.focus({ preventScroll: true });
    if (globalThis.innerWidth < 1050) reader.scrollIntoView({ behavior: 'instant', block: 'start' });
  };
  function draw() {
    if (!data) return;
    const filtered = findPassages(data, { ticker, query: search.value });
    if (!filtered.some(p => p.evidence_id === selected)) {
      // Start with a complete narrative, never the CNR table-heading-only candidate.
      selected = (filtered.find(p => p.research_id === 'CN-2025-02') || filtered[0])?.evidence_id;
    }
    $('#ed-companies').innerHTML = renderCompanyList(data, ticker);
    $('#ed-passages').innerHTML = renderPassageList(filtered, selected);
    $('#ed-company-title').textContent = COMPANIES[ticker]?.name || ticker;
    $('#ed-results').textContent = `${filtered.length} of ${data.passages.filter(p => p.subject_ticker === ticker).length} passages`;
    const p = current();
    $('#ed-reader').innerHTML = renderReader(p, data.documents.find(d => d.document_id === p?.document_id),
      data.holdings.find(h => h.ticker === ticker),
      { expert: doc.querySelector('[data-mode="expert"]')?.getAttribute('aria-pressed') === 'true' });
    if (p) {
      const open = doc.createElement('button');
      open.type = 'button'; open.className = 'rl-library-entry'; open.textContent = 'Read the full source page in the library →';
      open.addEventListener('click', () => doc.dispatchEvent(new CustomEvent('ripple:open-library', {
        detail: { ticker, hash: p.document_sha256, page: p.pdf_page },
      })));
      $('#ed-reader').append(open);
    }
    $('#ed-feedback').textContent = '';
  }
  async function load() {
    controller?.abort(); controller = new AbortController();
    const own = controller;
    status.hidden = false; status.textContent = 'Opening the local research file…';
    root.setAttribute('aria-busy', 'true'); $('#ed-workbench').hidden = true; $('#ed-retry').hidden = true;
    try {
      const loaded = await loadEvidence({ signal: own.signal });
      if (own.signal.aborted) return;
      data = loaded;
      if (!data.passages.length) { status.textContent = 'No documentary passages supplied in this local research file.'; return; }
      $('#ed-scope').textContent = `${data.holdings.length} companies · ${data.documents.length} reports · ${data.passages.length} passages`;
      $('#ed-weight').textContent = `${data.scope.documented_holding_weight_pct}%`;
      status.hidden = true; $('#ed-workbench').hidden = false; draw();
    } catch (error) {
      if (own.signal.aborted) return;
      status.textContent = `Research file unavailable. ${error.message} Serve frontend over local HTTP; no backend is needed.`;
      $('#ed-retry').hidden = false;
    } finally { if (!own.signal.aborted) root.setAttribute('aria-busy', 'false'); }
  }
  root.addEventListener('click', async event => {
    const company = event.target.closest('[data-company]');
    if (company && data) {
      ticker = company.dataset.company; selected = null; search.value = ''; draw();
      root.querySelector(`[data-company="${ticker}"]`)?.focus();
    }
    const passage = event.target.closest('[data-passage]');
    if (passage && data) { selected = passage.dataset.passage; draw(); focusReader(); }
    if (event.target.closest('[data-clear-search]')) { search.value = ''; draw(); search.focus(); }
    if (event.target.closest('[data-copy-citation]') && current()) {
      const p = current(), d = data.documents.find(item => item.document_id === p.document_id);
      try {
        await navigator.clipboard.writeText(citationText(p, d));
        $('#ed-feedback').textContent = 'Citation copied with page, hash and verification limits.';
      } catch { $('#ed-feedback').textContent = 'Clipboard access is unavailable. You can select and copy the quotation and verification details above.'; }
    }
    if (event.target.closest('#ed-retry')) load();
  });
  search.addEventListener('input', draw);
  const observer = new MutationObserver(() => { if (data) draw(); });
  doc.querySelectorAll('[data-mode]').forEach(b => observer.observe(b, { attributes: true, attributeFilter: ['aria-pressed'] }));
  doc.querySelector('#evidence-open')?.addEventListener('click', () => {
    root.scrollIntoView({ behavior: 'instant', block: 'start' });
    $('#ed-title').focus({ preventScroll: true });
  });
  load();
}

if (typeof document !== 'undefined') initEvidenceDesk();
