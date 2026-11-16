// Hover/focus explanations for the inline [measured] / [simulated] / [source] tags in agent answers.
// Everything is computed in the browser from the data the answer already carries (betas, scenario, risk
// shares, shields): the number just before a tag is matched to its stored figure and explained with the
// actual formula. No backend or agent change is involved.
import { escapeHTML as esc, finite, number } from './formatters.js';

const NUM_RE = /(-?\d+(?:[.,]\d+)?)\s*(%|bp)?\s*[)\]]*\s*$/;

/** The number written immediately before the tag, with its unit ('%' or 'bp') if any. */
export function lastNumber(before) {
  const m = String(before ?? '').replace(/[−–]/g, '-').trim().match(NUM_RE);
  return m ? { value: Number(m[1].replace(',', '.')), unit: m[2] ?? null } : null;
}

const near = (a, b, tol = 0.0051) => finite(a) && finite(b) && Math.abs(a - b) <= tol;
const li = parts => `<ul>${parts.filter(Boolean).map(p => `<li>${p}</li>`).join('')}</ul>`;
const F = (v, d = 3) => esc(number(v, d, true));
const range = (lo, hi, suffix = '') => (finite(lo) && finite(hi) ? `95% range ${F(lo, suffix ? 2 : 3)}${suffix} to ${F(hi, suffix ? 2 : 3)}${suffix}` : null);
const sub = s => (s === 'custom' ? 'your portfolio' : ['robert', 'amira', 'mateo'].includes(s) ? `${s[0].toUpperCase()}${s.slice(1)}’s portfolio` : s);

/**
 * { title, html } for one tag. `before` is the sentence text preceding the tag; `data` is the message's
 * compact data (risk, betas, scenario, shields, cushion); `trace` the agent steps.
 */
export function explainMeasured({ kind = 'measured', before = '', data = null, trace = [] } = {}) {
  if (kind === 'source') {
    return { title: 'Source passage', html: li([
      'Retrieved word for word from a stored document (annual report, central-bank research) by <code>search_evidence</code>.',
      'The bracketed citation under the answer links to the original; nothing is paraphrased by the model.']) };
  }
  if (kind === 'documented') {
    return { title: 'Documented', html: li(['Taken from an issuer or research document, cited under the answer.']) };
  }
  const d = data ?? {};
  const token = lastNumber(before);
  const v = token?.value ?? null;
  const scen = d.scenario ?? null;
  const betas = Array.isArray(d.betas) ? d.betas : [];
  const risk = d.risk && typeof d.risk === 'object' ? d.risk : {};
  const worst = [...(Array.isArray(d.shields) ? d.shields : []), ...(Array.isArray(d.cushion) ? d.cushion : [])];

  if (kind === 'simulated' || (scen && v !== null && (near(v, scen.impact) || near(Math.abs(v), Math.abs(scen.impact))))) {
    if (scen?.type === 'rates') {
      return { title: `Simulated: rates ${F(scen.shock, 0)} bp`, html: li([
        `Each holding's yield link (β per basis point, measured 2021–2026) is moved by ${F(scen.shock, 0)} bp; the weighted impacts sum to <b>${F(scen.impact, 2)}%</b>.`,
        range(scen.lo, scen.hi, '%'),
        'History pushed through a hypothetical shock — not a forecast.']) };
    }
    const beta = betas.find(b => b.subject === scen?.subject)?.beta ?? null;
    return { title: `Simulated: Brent ${F(scen?.shock, 0)}%`, html: li([
      '<code>impact = 100 × (e^(β · ln(1 + s/100)) − 1)</code>',
      beta !== null ? `β = ${F(beta)} (weekly oil sensitivity of ${esc(sub(scen.subject))}), s = ${F(scen.shock, 0)}% → <b>${F(scen.impact, 2)}%</b>` : `applied to the measured weekly beta → <b>${F(scen?.impact, 2)}%</b>`,
      range(scen?.lo, scen?.hi, '%'),
      'The 2021–2026 relationship applied to one hypothetical week — not a forecast.']) };
  }
  if (v !== null) {
    const b = betas.find(x => near(v, x.beta));
    if (b) {
      return { title: `Beta of ${esc(sub(b.subject))}`, html: li([
        '<code>β = Cov(r, r_brent) / Var(r_brent)</code> — the OLS slope of weekly returns on Brent weekly returns, 2021–2026 in CAD.',
        `β = <b>${F(b.beta)}</b>: a 1% Brent week moved it about ${F(b.beta)}% on average.`,
        range(b.lo, b.hi),
        finite(b.p) ? `p = ${esc(number(b.p, 3))} (HAC 4-lag standard errors)` : null]) };
    }
    const factor = Object.entries(risk).find(([, r]) => near(v, r));
    if (factor) {
      return { title: `Risk share: ${esc(factor[0])}`, html: li([
        `<code>R² = ${F(factor[1], 2)}</code> from a one-factor weekly regression: the share of the portfolio's weekly variance that ${esc(factor[0])} alone explains.`,
        'Each factor is regressed separately, so the three shares overlap and do not sum to 100%.']) };
    }
    const w = worst.find(x => near(v, x.avg) || (Number.isInteger(v) && (v === x.up || v === x.weeks)));
    if (w) {
      const name = esc(w.item ?? w.asset ?? 'This asset');
      return { title: 'Worst-weeks test', html: li([
        `The portfolio's worst 10% of weeks (${esc(w.weeks ?? '?')} weeks, 2021–2026) are isolated; ${name}'s average weekly return in them is <b>${F(w.avg, 2)}%</b>.`,
        finite(w.up) && finite(w.weeks) ? `It rose in ${esc(w.up)} of those ${esc(w.weeks)} weeks.` : null,
        finite(w.p) ? `Binomial test vs a coin flip: p = ${esc(number(w.p, 3))}. ${w.p > 0.1 ? 'About what chance would give.' : 'Unlikely to be chance.'}` : null]) };
    }
    if (scen && token.unit && (near(v, scen.shock) || near(Math.abs(v), Math.abs(scen.shock)))) {
      return { title: 'Assumed shock', html: li([`The hypothetical move being tested (${F(scen.shock, 0)}${scen.type === 'rates' ? ' bp' : '%'}), chosen for the scenario — an input, not a measurement.`]) };
    }
  }
  const tools = [...new Set((trace ?? []).map(t => t?.tool).filter(Boolean))];
  return { title: 'Measured', html: li([
    'Computed by the agent\'s tools from stored weekly data (2021–2026), never by the language model.',
    tools.length ? `Tools used here: ${tools.map(t => `<code>${esc(t)}</code>`).join(', ')}.` : null,
    'Open “How AION reasoned” for the exact tool call and its raw output.']) };
}

/** Text inside the tag's paragraph that precedes the tag. */
export function textBefore(tag) {
  let out = '';
  for (const node of tag.parentNode?.childNodes ?? []) {
    if (node === tag) break;
    out += node.textContent;
  }
  return out;
}

/** One shared tooltip for every tag in the thread. getMessage(i) returns the stored message. */
export function attachMeasuredTips(thread, getMessage, doc = document) {
  const tip = doc.createElement('div');
  tip.className = 'tag-tip';
  tip.setAttribute('role', 'tooltip');
  tip.id = 'tag-tip';
  tip.hidden = true;
  doc.body.append(tip);
  let current = null;
  const hide = () => { tip.hidden = true; current?.removeAttribute('aria-describedby'); current = null; };
  const show = tag => {
    const host = tag.closest('[data-mi]');
    const msg = host ? getMessage(Number(host.dataset.mi)) : null;
    const ex = explainMeasured({ kind: tag.dataset.kind, before: textBefore(tag), data: msg?.data, trace: msg?.trace });
    tip.innerHTML = `<b>${ex.title}</b>${ex.html}`;
    tip.hidden = false;
    const r = tag.getBoundingClientRect();
    const w = Math.min(340, doc.documentElement.clientWidth - 16);
    tip.style.maxWidth = `${w}px`;
    const left = Math.max(8, Math.min(r.left, doc.documentElement.clientWidth - w - 8));
    tip.style.left = `${left}px`;
    const below = r.bottom + 8 + tip.offsetHeight < doc.documentElement.clientHeight;
    tip.style.top = below ? `${r.bottom + 8}px` : `${Math.max(8, r.top - tip.offsetHeight - 8)}px`;
    current = tag;
    tag.setAttribute('aria-describedby', 'tag-tip');
  };
  const from = e => e.target.closest?.('.msg.assistant .ip-tag');
  thread.addEventListener('mouseover', e => { const t = from(e); if (t) show(t); });
  thread.addEventListener('mouseout', e => { if (from(e)) hide(); });
  thread.addEventListener('focusin', e => { const t = from(e); if (t) show(t); });
  thread.addEventListener('focusout', e => { if (from(e)) hide(); });
  doc.addEventListener('keydown', e => { if (e.key === 'Escape') hide(); });
  thread.addEventListener('scroll', hide, { passive: true });
  return { hide };
}
