// The agent answer's `data` object (docs/api_contract.md, built by lambdas/worker from tool results only):
// risk_share, shields, cushion, betas and scenario, shown as a compact "Measured results" card.
// twin_series (monthly drawdowns) and stock_bond_series (correlations) are drawn as small inline SVG charts.
import { escapeHTML as esc, finite, number } from './formatters.js';
import { SHIELDS } from './chat-tools.js';

const plain = v => v && typeof v === 'object' && !Array.isArray(v);
const num = v => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const str = v => (typeof v === 'string' && v.trim() ? v.trim().slice(0, 80) : null);
const rows = (v, max) => (Array.isArray(v) ? v.filter(plain).slice(0, max) : []);
const NAMES = Object.fromEntries(SHIELDS.map(s => [s.value, s.label]));
const nameOf = v => NAMES[v] ?? v;
const pct = v => (num(v) === null ? '—' : `${number(v, 2, true)}%`);

/** The part of `data` worth keeping with a chat message (small, numbers validated). */
export function compactData(data) {
  if (!plain(data)) return null;
  const risk = plain(data.risk_share) ? Object.fromEntries(['rates', 'stocks', 'oil'].filter(k => num(data.risk_share[k]) !== null).map(k => [k, data.risk_share[k]])) : {};
  const shields = rows(data.shields, 8).map(r => ({ item: str(r.item ?? r.ticker), label: str(r.label), avg: num(r.avg_pct_worst), up: num(r.weeks_up), weeks: num(r.weeks), p: num(r.binom_p), per100k: num(r.contribution_per_100k) }))
    .filter(r => r.item);
  const cushion = rows(data.cushion, 8).map(r => ({ asset: str(r.asset), avg: num(r.avg_return_pct), up: num(r.hit_weeks), weeks: num(r.n_weeks) })).filter(r => r.asset);
  const betas = rows(data.betas, 10).map(r => ({ subject: str(r.subject), beta: num(r.beta), lo: num(r.lo), hi: num(r.hi), p: num(r.p) })).filter(r => r.subject && r.beta !== null);
  const sc = plain(data.scenario) ? data.scenario : null;
  const scenario = sc && num(sc.impact_pct) !== null ? { subject: str(sc.subject), type: sc.shock_type === 'rates' ? 'rates' : 'oil',
    shock: num(sc.shock_type === 'rates' ? sc.shock_bp : sc.shock_pct), impact: num(sc.impact_pct), lo: num(sc.lo_pct), hi: num(sc.hi_pct) } : null;
  const twin = rows(data.twin_series, 240).map(r => ({ m: str(r.week), own: num(r.own_dd_pct), twin: num(r.twin_dd_pct) })).filter(r => r.m && (r.own !== null || r.twin !== null));
  const sb = rows(data.stock_bond_series, 600);
  const regimes = {};
  for (const r of sb) {
    const pair = str(r.pair);
    if (!pair || num(r.correlation) === null || !['cpi_ge_3', 'cpi_lt_3'].includes(r.measure)) continue;
    regimes[pair] ??= { pair };
    regimes[pair][r.measure === 'cpi_ge_3' ? 'high' : 'low'] = r.correlation;
    regimes[pair][r.measure === 'cpi_ge_3' ? 'nHigh' : 'nLow'] = num(r.n_weeks);
  }
  const rolling = {};
  for (const r of sb) {
    const pair = str(r.pair);
    if (r.measure !== 'rolling_52w' || !pair || !str(r.week) || num(r.correlation) === null) continue;
    if (!rolling[pair] && Object.keys(rolling).length >= 2) continue;
    (rolling[pair] ??= []).push({ m: str(r.week), c: r.correlation });
  }
  const stockBond = Object.keys(regimes).length || Object.keys(rolling).length ? { regimes: Object.values(regimes).slice(0, 4), rolling } : null;
  const out = { risk, shields, cushion, betas, scenario, twin: twin.length > 1 ? twin : [], stockBond };
  return Object.keys(risk).length || shields.length || cushion.length || betas.length || scenario || out.twin.length || stockBond ? out : null;
}

/** A small responsive line chart. series: [{name, cls, points: [{x: label, y: number|null}]}]. */
export function lineChart(series, { label, zero = true, fmt = v => number(v, 1, true) } = {}) {
  const pts = series.flatMap(s => s.points.filter(p => num(p.y) !== null));
  if (pts.length < 2) return '';
  const xs = series[0].points.map(p => p.x);
  let lo = Math.min(...pts.map(p => p.y)), hi = Math.max(...pts.map(p => p.y));
  if (zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  if (hi === lo) { hi += 1; lo -= 1; }
  const W = 600, H = 150, P = 6;
  const x = i => P + (i / Math.max(1, xs.length - 1)) * (W - 2 * P);
  const y = v => P + (1 - (v - lo) / (hi - lo)) * (H - 2 * P);
  const path = s => {
    let d = '', prev = false;
    s.points.forEach((p, i) => {
      if (num(p.y) === null) { prev = false; return; }
      d += `${prev ? ' L' : ' M'}${x(i).toFixed(1)},${y(p.y).toFixed(1)}`;
      prev = true;
    });
    return d.trim();
  };
  const shown = series.filter(s => s.points.some(p => num(p.y) !== null));
  return `<figure class="ad-chart"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(label)}">
      ${zero && lo < 0 && hi > 0 ? `<line class="ad-zero" x1="0" x2="${W}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}"/>` : ''}
      ${shown.map(s => `<path class="ad-line ${esc(s.cls)}" d="${path(s)}" vector-effect="non-scaling-stroke"/>`).join('')}
    </svg>
    <figcaption><span>${esc(xs[0])}</span><span class="ad-legend">${shown.map(s => `<span><i class="${esc(s.cls)}"></i>${esc(s.name)}</span>`).join('')}</span><span>${esc(xs.at(-1))}</span></figcaption>
    <p class="ad-range">Range ${esc(fmt(lo))} to ${esc(fmt(hi))}</p></figure>`;
}

const subject = s => (s === 'custom' ? 'Your portfolio' : ['robert', 'amira', 'mateo'].includes(s) ? `${s[0].toUpperCase()}${s.slice(1)}’s portfolio` : s);

/** HTML for the card, or '' when there is nothing measured to show. */
export function renderAnswerData(data) {
  const d = data && 'risk' in data ? data : compactData(data);
  if (!d) return '';
  const parts = [];
  if (d.scenario) {
    const s = d.scenario;
    const shock = s.type === 'rates' ? `rates ${number(s.shock, 0, true)} bp` : `Brent ${number(s.shock, 0, true)}%`;
    parts.push(`<div class="ad-hero"><span class="ad-k">${esc(subject(s.subject) ?? 'Portfolio')} · ${esc(shock)}</span>
      <span class="ad-v${s.impact < 0 ? ' neg' : ' pos'}">${pct(s.impact)}</span>
      <span class="ad-s">${s.lo !== null && s.hi !== null ? `95% range ${pct(s.lo)} to ${pct(s.hi)}` : 'No range for this estimate'}</span></div>`);
  }
  const risk = Object.entries(d.risk);
  if (risk.length) {
    parts.push(`<div class="ad-block"><p class="ad-title">What explains the weekly moves (R²)</p>${risk.map(([k, v]) => `<div class="ad-bar">
      <span>${esc(k[0].toUpperCase() + k.slice(1))}</span><span class="ad-track"><i style="width:${Math.max(0, Math.min(1, v)) * 100}%"></i></span><b>${number(v, 2)}</b></div>`).join('')}
      <p class="ad-note">Each factor is measured on its own, so the shares overlap and do not add up.</p></div>`);
  }
  const table = (title, head, body, note = '') => `<div class="ad-block"><p class="ad-title">${title}</p><div class="tbl"><table><thead><tr>${head.map(h => `<th>${h}</th>`).join('')}</tr></thead><tbody>${body}</tbody></table></div>${note}</div>`;
  if (d.twin?.length) {
    const worst = d.twin.reduce((w, r) => (r.own !== null && (w === null || r.own < w.own) ? r : w), null);
    parts.push(`<div class="ad-block"><p class="ad-title">Drawdown from the previous peak, monthly</p>${lineChart([
      { name: 'Your portfolio', cls: 'own', points: d.twin.map(r => ({ x: r.m, y: r.own })) },
      { name: 'Alternative twin', cls: 'twin', points: d.twin.map(r => ({ x: r.m, y: r.twin })) },
    ], { label: worst ? `Drawdown chart. Deepest: ${pct(worst.own)} in ${worst.m}.` : 'Drawdown chart', fmt: v => `${number(v, 1, true)}%` })}
      ${worst ? `<p class="ad-note">Deepest drawdown ${pct(worst.own)} (${esc(worst.m)}).</p>` : ''}</div>`);
  }
  if (d.stockBond) {
    const [pair, line] = Object.entries(d.stockBond.rolling)[0] ?? [];
    if (line?.length > 1) {
      parts.push(`<div class="ad-block"><p class="ad-title">Stock–bond correlation, 52-week rolling (${esc(pair)})</p>${lineChart([
        { name: pair, cls: 'own', points: line.map(r => ({ x: r.m, y: r.c })) }], { label: `Rolling stock–bond correlation for ${pair}`, fmt: v => number(v, 2, true) })}
        <p class="ad-note">Above zero, stocks and bonds moved together; below zero, bonds tended to offset stocks.</p></div>`);
    }
    if (d.stockBond.regimes.length) {
      const cell = (v, n) => (num(v) === null ? '—' : `${number(v, 2, true)}${n ? ` <small>(${n} wk)</small>` : ''}`);
      parts.push(table('Stock–bond correlation by inflation regime', ['Pair', 'Inflation ≥ 3%', 'Inflation < 3%'],
        d.stockBond.regimes.map(r => `<tr><td>${esc(r.pair)}</td><td>${cell(r.high, r.nHigh)}</td><td>${cell(r.low, r.nLow)}</td></tr>`).join('')));
    }
  }
  if (d.shields.length) {
    const money = d.shields.some(r => r.per100k !== null);
    const usd = v => (v === null ? '—' : `${v < 0 ? '−' : '+'}$${Math.abs(v).toLocaleString('en-CA', { maximumFractionDigits: 0 })}`);
    parts.push(table('Shields in the worst weeks', ['Shield', 'Result', 'Avg in worst weeks', 'Weeks up', ...(money ? ['Per $100k'] : [])],
      d.shields.map(r => `<tr><td>${esc(nameOf(r.item))}</td><td>${r.label ? `<span class="verdict mini" data-verdict="${esc(r.label.toLowerCase().replace(/\s+/g, '-'))}">${esc(r.label)}</span>` : '—'}</td><td>${pct(r.avg)}</td><td>${r.up !== null && r.weeks !== null ? `${r.up} of ${r.weeks}` : '—'}</td>${money ? `<td>${usd(r.per100k)}</td>` : ''}</tr>`).join('')));
  }
  if (d.cushion.length) {
    parts.push(table('What cushioned the worst stock weeks', ['Asset', 'Avg return', 'Weeks up'],
      d.cushion.map(r => `<tr><td>${esc(nameOf(r.asset))}</td><td>${pct(r.avg)}</td><td>${r.up !== null && r.weeks !== null ? `${r.up} of ${r.weeks}` : '—'}</td></tr>`).join('')));
  }
  if (d.betas.length) {
    parts.push(table('Oil sensitivity', ['Subject', 'Beta', '95% range'],
      d.betas.map(r => `<tr><td>${esc(subject(r.subject))}</td><td>${number(r.beta, 3, true)}</td><td>${r.lo !== null && r.hi !== null ? `${number(r.lo, 3, true)} to ${number(r.hi, 3, true)}` : '—'}</td></tr>`).join('')));
  }
  return `<section class="answer-data" aria-label="Measured results"><p class="ad-head"><span class="ip-tag" data-kind="measured">measured</span>Results from the tools, 2021–2026</p>${parts.join('')}</section>`;
}
