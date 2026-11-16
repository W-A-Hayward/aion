// 3D passage wall: a vanilla port of the "3D testimonials" Marquee pattern (vertical columns that scroll in
// alternating directions, pause on hover, tilted in perspective). The cards are real annual-report passages from
// evidence-preview.json, with original wording and page numbers. Clicking a card opens that report, at that page,
// in the source library (the shell listens for ripple:show-source).
const stage = document.querySelector('#quotes-stage');
const reduce = matchMedia('(prefers-reduced-motion: reduce)');
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const clip = (s, n) => (s.length > n ? `${s.slice(0, n).replace(/\s+\S*$/, '')}…` : s);

function card(p, issuer, hidden) {
  const tag = p.research_id.split('-')[0];
  return `<button type="button" class="q-card" data-q-ticker="${esc(p.subject_ticker)}" data-q-hash="${esc(p.document_sha256 ?? '')}" data-q-page="${esc(p.pdf_page)}"${hidden ? ' tabindex="-1"' : ''}>
    <span class="q-top"><b>${esc(tag)}</b><span>${esc(issuer)}</span></span>
    <q>${esc(clip(p.excerpt_original, 190))}</q>
    <small>${esc(p.research_id)} · PDF p. ${esc(p.pdf_page)}</small>
  </button>`;
}

function column(items, reverse, duration) {
  const group = hidden => `<div class="q-group"${hidden ? ' aria-hidden="true"' : ''}>${items.map(([p, i]) => card(p, i, hidden)).join('')}</div>`;
  return `<div class="q-col${reverse ? ' reverse' : ''}" style="--duration:${duration}s">${group(false)}${group(true)}</div>`;
}

function openPassage(ticker, hash, page) {
  document.dispatchEvent(new CustomEvent('ripple:show-source', { detail: { ticker, ...(hash ? { hash } : {}), ...(Number(page) ? { page: Number(page) } : {}) } }));
}

async function init() {
  if (!stage) return;
  let data;
  try { data = await (await fetch('./evidence-preview.json')).json(); } catch { stage.closest('.quotes')?.setAttribute('hidden', ''); return; }
  const issuers = new Map(data.documents.map(d => [d.document_id, (d.issuer || '').replace(/ (Limited|Company|Inc\.|Ltd\.?)$/i, '')]));
  // Interleave companies so neighbouring cards differ.
  // The wall shows prose only; passages that are mostly figures (table rows) are left out.
  const prose = data.passages.filter(p => (p.excerpt_original.match(/[\d.,%–-]/g) || []).length / p.excerpt_original.length < 0.25);
  const byTicker = Map.groupBy(prose, p => p.subject_ticker);
  const mixed = [];
  for (let i = 0; mixed.length < prose.length; i++) for (const list of byTicker.values()) if (list[i]) mixed.push(list[i]);
  const cols = [[], [], [], []];
  mixed.forEach((p, i) => cols[i % 4].push([p, issuers.get(p.document_id) || p.subject_ticker]));
  stage.innerHTML = `<div class="q-plane">${cols.map((c, i) => column(c, i % 2 === 1, 46 + i * 6)).join('')}</div>`;
  stage.addEventListener('click', e => {
    const b = e.target.closest('.q-card');
    if (b) openPassage(b.dataset.qTicker, b.dataset.qHash, b.dataset.qPage);
  });
}
init();
