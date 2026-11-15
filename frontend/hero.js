// Opening "ripple" figure. Every dot is a real saved estimate from preview-data.json:
// x = Brent beta (compressed scale), whisker = 95% range, bob height on each wave = beta.
// Purely presentational; clicking a dot opens the existing research view for that ticker.
import { CORE_TICKERS, TICKER_INFO } from './config.js';
import { shortTicker } from './formatters.js';

const NS = 'http://www.w3.org/2000/svg';
const host = document.querySelector('#hero-figure');
const tip = document.querySelector('#hero-tip');
const reduce = matchMedia('(prefers-reduced-motion: reduce)');
const scaleB = b => Math.asinh(b / 0.03);           // spreads the many near-zero betas apart
const TICKS = [-0.1, -0.05, 0, 0.05, 0.1, 0.2, 0.4];
let rows = [];
let frame = 0;
let layout = null;

const el = (name, attrs = {}, parent) => {
  const node = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  parent?.append(node);
  return node;
};
const fmt = (v, d = 3) => (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d);
const impact = (beta, shock) => 100 * (Math.exp(beta * Math.log(1 + shock / 100)) - 1);

function build() {
  if (!host || !rows.length) return;
  const W = Math.max(320, host.clientWidth);
  const narrow = W < 720;
  const H = narrow ? 440 : 400;
  const pad = narrow ? 28 : 64;
  const lo = scaleB(-0.12), hi = scaleB(0.45);
  const X = b => pad + (scaleB(b) - lo) / (hi - lo) * (W - 2 * pad);
  const axisY = H * 0.56;
  const x0 = X(0);

  // Greedy lanes, alternating above/below the axis, so labels never collide.
  const gap = narrow ? 58 : 76, laneH = narrow ? 34 : 40;
  const order = [0, -1, 1, -2, 2, -3, 3, -4, 4];
  const lanes = new Map();
  const dots = [...rows].sort((a, b) => a.beta - b.beta).map(r => {
    const x = X(r.beta);
    const lane = order.find(l => (lanes.get(l) ?? -1e9) < x - gap && l !== 0) ?? order.at(-1);
    lanes.set(lane, x);
    const y = axisY + lane * laneH;
    return { ...r, x, y, d: Math.hypot(x - x0, y - axisY) };
  });

  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'group',
    'aria-label': 'Brent oil beta of each supported ticker. Select one to open its research.' });
  const rings = el('g', { class: 'hr-rings' }, svg);
  el('line', { class: 'hr-axis', x1: pad - 12, x2: W - pad + 12, y1: axisY, y2: axisY }, svg);
  for (const t of TICKS) {
    const x = X(t);
    el('line', { class: t === 0 ? 'hr-zero' : 'hr-grid', x1: x, x2: x, y1: 26, y2: H - 30 }, svg);
    if (narrow && (t === -0.05 || t === 0.05)) continue;
    el('text', { class: 'hr-tick', x, y: H - 10, 'text-anchor': 'middle' }, svg).textContent = t === 0 ? '0' : fmt(t, 2).replace(/0+$/, '').replace(/\.$/, '');
  }
  el('text', { class: 'hr-side', x: pad - 12, y: 18 }, svg).textContent = '← falls when oil rises';
  el('text', { class: 'hr-side', x: W - pad + 12, y: 18, 'text-anchor': 'end' }, svg).textContent = 'rises with oil →';

  // Oil source
  const src = el('g', { class: 'hr-source', transform: `translate(${x0} ${axisY})` }, svg);
  el('circle', { r: 15, class: 'hr-source-halo' }, src);
  el('path', { d: 'M0-10C0-10-7-1-7 3.5a7 7 0 0 0 14 0C7-1 0-10 0-10z', class: 'hr-drop' }, src);

  const nodes = dots.map(d => {
    const cls = d.sig ? (d.beta > 0 ? 'pos' : 'neg') : 'ns';
    const g = el('g', { class: `hr-dot ${cls}`, tabindex: 0, role: 'button', 'data-ticker': d.ticker,
      'aria-label': `${shortTicker(d.ticker)}, ${d.name}: beta ${fmt(d.beta)}, 95% range ${fmt(d.lo)} to ${fmt(d.hi)}${d.sig ? '' : ', range crosses zero'}. Open research.` }, svg);
    const inner = el('g', {}, g);
    el('line', { class: 'hr-ci', x1: X(d.lo) - d.x, x2: X(d.hi) - d.x, y1: 0, y2: 0 }, inner);
    el('circle', { class: 'hr-hit', r: 20 }, inner);
    el('circle', { class: 'hr-pt', r: d.sig ? 6 : 5 }, inner);
    el('text', { class: 'hr-label', y: d.y <= axisY ? -13 : 22, 'text-anchor': 'middle' }, inner).textContent = shortTicker(d.ticker);
    g.setAttribute('transform', `translate(${d.x} ${d.y})`);
    return { d, g, inner, amp: Math.sign(d.beta) * Math.min(24, Math.max(2, Math.abs(d.beta) * 70)) };
  });

  host.replaceChildren(svg);
  layout = { svg, rings, nodes, x0, axisY, maxR: Math.hypot(Math.max(x0, W - x0), H), W };
}

function animate(t0) {
  cancelAnimationFrame(frame);
  if (!layout || reduce.matches) return;
  const speed = 210, every = 3.2, width = 46;
  const tick = now => {
    const t = (now - t0) / 1000;
    const { rings, nodes, x0, axisY, maxR } = layout;
    const radii = [];
    for (let k = Math.floor(t / every); k >= 0; k--) {
      const r = (t - k * every) * speed;
      if (r > maxR) break;
      radii.push(r);
    }
    while (rings.childElementCount < radii.length) el('circle', { class: 'hr-ring', cx: x0, cy: axisY }, rings);
    [...rings.children].forEach((c, i) => {
      const r = radii[i];
      if (r === undefined) { c.setAttribute('r', 0); c.style.opacity = 0; return; }
      c.setAttribute('r', r.toFixed(1));
      c.style.opacity = (1 - r / maxR) * 0.55;
    });
    for (const n of nodes) {
      let off = 0;
      for (const r of radii) off += Math.exp(-(((n.d.d - r) / width) ** 2));
      n.inner.setAttribute('transform', `translate(0 ${(-n.amp * Math.min(1, off)).toFixed(2)})`);
    }
    frame = requestAnimationFrame(tick);
  };
  frame = requestAnimationFrame(tick);
}

function showTip(g) {
  const d = layout?.nodes.find(n => n.g === g)?.d;
  if (!d || !tip) return;
  const box = host.getBoundingClientRect(), r = g.getBoundingClientRect();
  tip.innerHTML = `<b>${shortTicker(d.ticker)}</b> <span>${d.name}</span>
    <dl><div><dt>Brent beta</dt><dd>${fmt(d.beta)}</dd></div>
    <div><dt>95% range</dt><dd>${fmt(d.lo)} to ${fmt(d.hi)}</dd></div>
    <div><dt>If Brent +30%</dt><dd>${fmt(impact(d.beta, 30), 2)}%</dd></div></dl>
    <small>${d.sig ? 'Range excludes zero.' : 'Range crosses zero: direction not settled.'} Click to open.</small>`;
  tip.hidden = false;
  const left = Math.min(box.width - tip.offsetWidth - 8, Math.max(8, r.left - box.left + r.width / 2 - tip.offsetWidth / 2));
  const above = r.top - box.top - tip.offsetHeight - 10;
  tip.style.left = `${left}px`;
  tip.style.top = `${above > 0 ? above : r.bottom - box.top + 10}px`;
}

function open(ticker) {
  document.querySelector('[data-view="research"]')?.click();
  requestAnimationFrame(() => {
    document.querySelector(`#field [data-ticker="${CSS.escape(ticker)}"]`)?.click();
    document.querySelector('#pick')?.scrollIntoView({ behavior: reduce.matches ? 'auto' : 'smooth', block: 'start' });
  });
}

host?.addEventListener('pointerover', e => { const g = e.target.closest('.hr-dot'); if (g) showTip(g); });
host?.addEventListener('pointerout', e => { if (!e.relatedTarget?.closest?.('.hr-dot')) tip.hidden = true; });
host?.addEventListener('focusin', e => { const g = e.target.closest('.hr-dot'); if (g) showTip(g); });
host?.addEventListener('focusout', () => { tip.hidden = true; });
host?.addEventListener('click', e => { const g = e.target.closest('.hr-dot'); if (g) open(g.dataset.ticker); });
host?.addEventListener('keydown', e => {
  const g = e.target.closest('.hr-dot');
  if (g && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); open(g.dataset.ticker); }
});

document.querySelectorAll('[data-hero-jump]').forEach(b => b.addEventListener('click', () => {
  document.querySelector(b.dataset.heroJump)?.scrollIntoView({ behavior: reduce.matches ? 'auto' : 'smooth', block: 'start' });
  if (b.dataset.heroJump === '#ask') setTimeout(() => document.querySelector('#question')?.focus({ preventScroll: true }), 400);
}));

// Count-up for the headline numbers (final values are already in the HTML).
function countUp() {
  if (reduce.matches) return;
  document.querySelectorAll('[data-count]').forEach(node => {
    const end = Number(node.dataset.count), start = performance.now();
    const step = now => {
      const p = Math.min(1, (now - start) / 1100);
      node.textContent = Math.round(end * (1 - (1 - p) ** 3)).toLocaleString('en-CA');
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}

// Reveal sections as they scroll in. Content is visible by default if this never runs.
function reveal() {
  if (reduce.matches || !('IntersectionObserver' in globalThis)) return;
  const targets = document.querySelectorAll('.chat-entry .ask, .evidence-desk, .research-library, .workspace, .foot');
  const io = new IntersectionObserver(entries => entries.forEach(e => {
    if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
  }), { rootMargin: '0px 0px -8% 0px' });
  document.documentElement.classList.add('reveal-ready');
  targets.forEach(t => io.observe(t));
}

async function init() {
  reveal();
  try {
    const data = await (await fetch('./preview-data.json')).json();
    rows = data.sensitivities.filter(r => CORE_TICKERS.includes(r.ticker) && Number.isFinite(r.beta_simple))
      .map(r => ({ ticker: r.ticker, name: TICKER_INFO[r.ticker].name, beta: r.beta_simple, lo: r.lo_simple, hi: r.hi_simple,
        sig: r.lo_simple > 0 || r.hi_simple < 0 }));
  } catch {
    host?.closest('.hero-chart')?.setAttribute('hidden', '');
    return;
  }
  build();
  animate(performance.now());
  countUp();
  let timer;
  new ResizeObserver(() => { clearTimeout(timer); timer = setTimeout(() => { build(); animate(performance.now()); }, 120); }).observe(host);
  reduce.addEventListener?.('change', () => animate(performance.now()));
}
init();
