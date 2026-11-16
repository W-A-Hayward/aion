// Statistics view: weekly Brent sensitivities read live from the backend (GET /research, lambdas/research).
// Nothing is computed from a local file; if the API is unavailable the view says so and offers a retry.
import { CORE_TICKERS, TICKER_INFO } from './config.js';
import { escapeHTML as esc, finite, number, probability, shortTicker, sourceURL } from './formatters.js';
import { loadInvestigation } from './api.js';
import { lineChart } from './answer-data.js';

const pct = v => (finite(v) ? `${number(v, 2, true)}%` : '—');
const range = (lo, hi, d = 3) => (finite(lo) && finite(hi) ? `${number(lo, d, true)} to ${number(hi, d, true)}` : '—');
const direction = r => (r.lo_simple > 0 ? 'tended to rise with oil' : r.hi_simple < 0 ? 'tended to fall when oil rose' : 'had no settled direction: the range crosses zero');

/** Ranked bars of every ticker's beta with its 95% range on one shared scale. */
export function betaRanking(rows, selected) {
  const list = rows.filter(r => CORE_TICKERS.includes(r.ticker) && finite(r.beta_simple)).sort((a, b) => b.beta_simple - a.beta_simple);
  if (!list.length) return '';
  const lo = Math.min(0, ...list.map(r => r.lo_simple ?? r.beta_simple)), hi = Math.max(0, ...list.map(r => r.hi_simple ?? r.beta_simple));
  const x = v => ((v - lo) / (hi - lo || 1)) * 100;
  return `<div class="rank" role="list" aria-label="Weekly Brent beta by ticker, with 95% ranges">${list.map(r => `
    <button type="button" class="rank-row" role="listitem" data-stats-ticker="${esc(r.ticker)}"${r.ticker === selected ? ' aria-current="true"' : ''}>
      <span class="rank-t">${esc(shortTicker(r.ticker))}</span>
      <span class="rank-track"><i class="rank-zero" style="left:${x(0)}%"></i>${finite(r.lo_simple) && finite(r.hi_simple) ? `<i class="rank-ci" style="left:${x(r.lo_simple)}%;width:${Math.max(0.5, x(r.hi_simple) - x(r.lo_simple))}%"></i>` : ''}<i class="rank-dot${r.beta_simple < 0 ? ' neg' : ''}" style="left:${x(r.beta_simple)}%"></i></span>
      <span class="rank-v">${number(r.beta_simple, 3, true)}</span></button>`).join('')}</div>`;
}

export function tickerDetail(tables, ticker, meta = {}) {
  const row = tables.sensitivities.find(r => r.ticker === ticker);
  if (!row || !finite(row.beta_simple)) return `<p class="stats-empty">The backend returned no estimate for ${esc(shortTicker(ticker))}.</p>`;
  const conf = tables.confidence.find(r => r.ticker === ticker);
  const scen = tables.scenarios.filter(r => r.subject === ticker && finite(r.shock_pct)).sort((a, b) => a.shock_pct - b.shock_pct);
  const rolling = tables.rolling.filter(r => r.ticker === ticker && finite(r.beta_52w));
  const chains = tables.chain_reconciliation.filter(r => r.ticker === ticker);
  const evidence = tables.evidence.filter(r => r.ticker === ticker || r.ticker === 'macro').slice(0, 3);
  const kpi = (k, v, s = '') => `<div class="kpi"><span class="kpi-k">${k}</span><span class="kpi-v">${v}</span>${s ? `<span class="kpi-s">${s}</span>` : ''}</div>`;
  const oos = finite(row.oos_hit_rate) && finite(row.oos_n) && row.oos_n > 0 ? `${Math.round(row.oos_hit_rate * row.oos_n)} of ${row.oos_n} big-move weeks` : '—';
  return `
    <div class="stats-headline">
      <h2 id="stats-ticker-title">${esc(shortTicker(ticker))} <span>${esc(TICKER_INFO[ticker]?.name ?? '')}</span></h2>
      <p>Over ${number(row.n_weeks, 0)} weeks it ${direction(row)}.${conf?.label ? ` Confidence: <span class="verdict mini" data-verdict="${esc(String(conf.label).toLowerCase())}">${esc(conf.label)}</span>` : ''}</p>
      ${conf?.reason_text ? `<p class="fine">${esc(conf.reason_text)}</p>` : ''}
    </div>
    <div class="kpis">
      ${kpi('Weekly Brent beta', number(row.beta_simple, 3, true), `95% range ${range(row.lo_simple, row.hi_simple)}`)}
      ${kpi('Controlling for the market', finite(row.beta_mkt) ? number(row.beta_mkt, 3, true) : '—', finite(row.beta_mkt) ? `95% range ${range(row.lo_mkt, row.hi_mkt)}` : '')}
      ${kpi('Significance', `p ${probability(row.p_simple)}`, finite(row.q_simple) ? `q ${probability(row.q_simple)} across the universe` : '')}
      ${kpi('Out of sample', oos, 'Direction called right, fitted to 2024')}
    </div>
    ${scen.length ? `<section class="stats-block"><h3>Brent shock scenarios</h3><p class="fine">One-week move, applied to the historical beta. A statistical scenario, not a forecast.</p>
      <div class="scen">${scen.map(s => `<div class="scen-c"><span class="scen-k">Brent ${number(s.shock_pct, 0, true)}%</span><span class="scen-v${s.impact_pct < 0 ? ' neg' : ' pos'}">${pct(s.impact_pct)}</span><span class="scen-s">${pct(s.lo_pct)} to ${pct(s.hi_pct)}</span></div>`).join('')}</div></section>` : ''}
    ${rolling.length > 1 ? `<section class="stats-block"><h3>How the beta changed: 52-week rolling</h3>${lineChart([{ name: `${shortTicker(ticker)} 52-week beta`, cls: 'own', points: rolling.map(r => ({ x: String(r.week).slice(0, 7), y: r.beta_52w })) }], { label: `Rolling 52-week Brent beta for ${shortTicker(ticker)}`, fmt: v => number(v, 2, true) })}</section>` : ''}
    <section class="stats-block"><h3>Robustness</h3>
      <div class="tbl"><table><tbody>
        <tr><th>Without 2022</th><td>${finite(row.beta_ex2022) ? number(row.beta_ex2022, 3, true) : '—'}</td><td>p ${probability(row.p_ex2022)}</td></tr>
        <tr><th>Oil up weeks / down weeks</th><td>${finite(row.beta_up) ? number(row.beta_up, 3, true) : '—'}</td><td>${finite(row.beta_down) ? number(row.beta_down, 3, true) : '—'}</td></tr>
      </tbody></table></div></section>
    ${chains.length ? `<section class="stats-block"><h3>Measured pathways</h3><ul class="chains">${chains.map(c => `<li><code>${esc(String(c.chain).replaceAll('>', ' → '))}</code> ${finite(c.beta_chain) ? `gives ${number(c.beta_chain, 3, true)}` : ''}${finite(c.share_explained) && c.share_explained >= 0 && c.share_explained <= 1.2 ? `, about ${Math.round(c.share_explained * 100)}% of the direct beta` : ', which does not line up with the direct beta'}.</li>`).join('')}</ul><p class="fine">A statistical pathway, not a proven cause.</p></section>` : ''}
    ${evidence.length ? `<section class="stats-block"><h3>Sources</h3>${evidence.map(e => { const link = sourceURL(e.source_url); return `<figure class="quote"><blockquote>${esc(e.excerpt)}</blockquote><figcaption><b>${esc(e.ticker)}</b> ${esc(e.section || e.doc_type || '')}${link ? ` · <a href="${esc(link)}" target="_blank" rel="noopener noreferrer">source ↗</a>` : ''}</figcaption></figure>`; }).join('')}</section>` : ''}
    <p class="fine">From the RIPPLE backend${meta.as_of ? `, data to ${esc(meta.as_of)}` : ''}${Array.isArray(meta.missing) && meta.missing.length ? `. Not available in this response: ${esc(meta.missing.join(', '))}` : ''}.</p>`;
}

export function mountStatistics(host, { load = loadInvestigation } = {}) {
  let ticker = 'XIU.TO', controller = null;
  host.innerHTML = `<header class="page-head">
      <p class="eyebrow-text">Statistics</p>
      <h1 id="stats-title">How each ticker moved with oil</h1>
      <p class="lede">Weekly Brent sensitivities, ranges and scenarios for the 14 supported tickers, read live from the RIPPLE backend.</p>
    </header>
    <div class="stats-controls"><label>Ticker <select id="stats-ticker">${CORE_TICKERS.map(t => `<option value="${t}">${esc(shortTicker(t))} · ${esc(TICKER_INFO[t].name)}</option>`).join('')}</select></label>
      <span class="src-badge"><i></i>Live backend</span></div>
    <div id="stats-body" aria-live="polite"></div>`;
  const body = host.querySelector('#stats-body'), select = host.querySelector('#stats-ticker');
  const run = async () => {
    controller?.abort(); controller = new AbortController();
    select.value = ticker;
    body.innerHTML = '<p class="stats-loading" role="status">Loading from the backend…</p>';
    try {
      const { tables, meta } = await load({ ticker, signal: controller.signal });
      body.innerHTML = `<div class="stats-grid"><section class="stats-block rank-block"><h3>All tickers</h3><p class="fine">Beta and 95% range; select one.</p>${betaRanking(tables.sensitivities, ticker)}</section>
        <section class="stats-main" aria-labelledby="stats-ticker-title">${tickerDetail(tables, ticker, meta)}</section></div>`;
    } catch (error) {
      if (controller.signal.aborted) return;
      body.innerHTML = `<div class="stats-error" role="alert"><b>Statistics unavailable</b><p>${esc(error.message)}</p><p class="fine">The agent still answers questions about these tickers.</p>
        <div class="page-actions"><button type="button" class="btn primary sm" data-stats-retry>Try again</button><button type="button" class="btn ghost sm" data-go="agent">Ask the agent</button></div></div>`;
    }
  };
  select.addEventListener('change', () => { ticker = select.value; run(); });
  host.addEventListener('click', e => {
    const t = e.target.closest('[data-stats-ticker]');
    if (t) { ticker = t.dataset.statsTicker; run(); }
    if (e.target.closest('[data-stats-retry]')) run();
  });
  return { refresh: run, select: t => { ticker = t; run(); } };
}
