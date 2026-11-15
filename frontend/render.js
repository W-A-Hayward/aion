import { escapeHTML as esc, finite, number, percent, interval, probability, sourceURL, shortTicker, nodeLabel, hasEstimate } from './formatters.js';
import { TICKER_INFO } from './config.js';

const info = ticker => TICKER_INFO[ticker] || { name: shortTicker(ticker), blurb: '', kind: 'etf' };
const isStock = ticker => info(ticker).kind === 'stock';

const crossesZero = row => row.lo_simple <= 0 && row.hi_simple >= 0;
export const direction = row => crossesZero(row) ? 'flat' : row.beta_simple < 0 ? 'down' : 'up';

// Final formatted text is rendered immediately; app.js may animate toward it.
const counter = (key, value, digits, suffix = '') =>
  `<span data-count="${esc(key)}" data-value="${value}" data-digits="${digits}" data-suffix="${esc(suffix)}">${number(value, digits, true)}${esc(suffix)}</span>`;

export function intervalPlot(value, lo, hi, { unit = '', label = '95% coefficient interval', domain } = {}) {
  if (![value, lo, hi].every(finite)) return '<p class="note">Range unavailable.</p>';
  const a = domain?.[0] ?? Math.min(lo, 0), b = domain?.[1] ?? Math.max(hi, 0);
  const padding = Math.max((b - a) * .12, .001);
  const min = a - padding, max = b + padding;
  const x = n => 12 + ((n - min) / (max - min)) * 376;
  const title = `${label}: ${number(lo, 3, true)} to ${number(hi, 3, true)}${unit}; estimate ${number(value, 3, true)}${unit}.`;
  return `<svg class="range-plot" viewBox="0 0 400 54" role="img" aria-label="${esc(title)}">
    <line class="axis" x1="12" y1="22" x2="388" y2="22"/>
    <line class="zero" x1="${x(0)}" y1="6" x2="${x(0)}" y2="36"/>
    <rect class="band" x="${x(lo)}" y="17" width="${Math.max(x(hi) - x(lo), 1)}" height="10" rx="5"/>
    <circle class="dot" cx="${x(value)}" cy="22" r="6"/>
    <text x="${x(lo)}" y="48" text-anchor="middle">${number(lo, 2, true)}${esc(unit)}</text>
    <text x="${x(hi)}" y="48" text-anchor="middle">${number(hi, 2, true)}${esc(unit)}</text>
  </svg>`;
}

export function renderHero(host, row, expert, confidence) {
  const t = esc(shortTicker(row.ticker));
  const dir = direction(row);
  const b = number(row.beta_simple, 3, true), lo = number(row.lo_simple, 3, true), hi = number(row.hi_simple, 3, true);
  const weeks = number(row.n_weeks, 0);
  const verdict = { flat: 'No clear direction', down: 'Tends to fall when oil rises', up: 'Tends to rise with oil' }[dir];
  const reading = dir === 'flat'
    ? `On average, a 1% move in Brent came with a ${b}% move in ${t}, but the 95% range (${lo} to ${hi}) includes zero, so the direction isn’t established. That is not the same as having no exposure.`
    : `On average, a 1% move in Brent came with a ${b}% move in ${t}. The 95% range (${lo} to ${hi}) is entirely ${dir === 'down' ? 'below' : 'above'} zero. The data doesn’t say why.`;
  const without2022 = finite(row.p_ex2022) ? (row.p_ex2022 < .05 ? 'Holds (p < 0.05)' : `Not significant (p ${probability(row.p_ex2022)})`) : 'Unavailable';
  host.innerHTML = `<div class="hero-copy is-${dir}">
    <div class="hero-top">
      <div><h1 id="page-title">${t} <span class="hero-name">${esc(info(row.ticker).name)}</span></h1>
      <p class="hero-sub">${esc(row.ticker)} · ${isStock(row.ticker) ? 'Stock' : 'ETF'} · ${esc(info(row.ticker).blurb)}</p></div>
    </div>
    <div class="hero-figure">
      <div class="beta"><span class="beta-label">Oil beta</span><span class="beta-num">${counter('beta', row.beta_simple, 3)}</span><span class="verdict ${dir}">${verdict}</span></div>
      <div class="beta-range"><span class="beta-label">95% range ${interval(row.lo_simple, row.hi_simple)}</span>${intervalPlot(row.beta_simple, row.lo_simple, row.hi_simple)}</div>
      <dl class="facts">
        <div><dt>Sample</dt><dd>${weeks} weeks</dd></div>
        <div><dt>Excluding 2022</dt><dd>${without2022}</dd></div>
        <div><dt>p-value</dt><dd>${probability(row.p_simple)}</dd></div>
      </dl>
    </div>
    <p class="reading">${reading} ${expert
      ? `OLS on weekly CAD log returns vs Brent log returns, HAC(4); adjusted q = ${probability(row.q_simple)}.`
      : isStock(row.ticker) ? 'Beta measures co-movement of the share price, not how much of the business depends on oil.'
        : 'Beta measures co-movement, not how much of the fund is invested in energy.'}${confidence ? ` Pipeline confidence: ${esc(confidence.label)}, ${esc(confidence.reason_text)}.` : ''}</p>
  </div>`;
}

export function renderField(host, tables, tickers, selected) {
  const rows = tickers.map(ticker => ({ ticker, row: tables?.sensitivities.find(item => item.ticker === ticker) }));
  const valid = rows.map(item => item.row).filter(hasEstimate);
  let min = Math.min(0, ...valid.map(row => row.lo_simple)), max = Math.max(0, ...valid.map(row => row.hi_simple));
  if (min === max) { min = -1; max = 1; }
  const pad = (max - min) * .06; min -= pad; max += pad;
  const x = value => (value - min) / (max - min) * 100;
  host.style.setProperty('--zero', `${x(0).toFixed(2)}%`);
  host.innerHTML = rows.map(({ ticker, row }, i) => {
    const newGroup = i === 0 || info(ticker).kind !== info(rows[i - 1].ticker).kind;
    const divider = newGroup ? `<p class="field-group" aria-hidden="true">${isStock(ticker) ? 'Stocks' : 'ETFs'}</p>` : '';
    const ok = hasEstimate(row);
    const dir = ok ? direction(row) : 'none';
    const label = ok ? `${ticker}, oil beta ${number(row.beta_simple, 3, true)}, range ${interval(row.lo_simple, row.hi_simple)}` : `${ticker}, no estimate loaded`;
    return `${divider}<button type="button" class="field-row ${dir}" data-ticker="${esc(ticker)}" aria-pressed="${ticker === selected}" aria-label="${esc(label)}" style="--i:${i}">
      <span class="field-name"><b>${esc(shortTicker(ticker))}</b><small>${esc(info(ticker).blurb)}</small></span>
      <span class="field-track">${ok ? `<i class="field-range" style="left:${x(row.lo_simple).toFixed(2)}%;width:${Math.max(x(row.hi_simple) - x(row.lo_simple), .6).toFixed(2)}%"></i><i class="field-dot" style="left:${x(row.beta_simple).toFixed(2)}%"></i>` : ''}</span>
      <span class="field-value">${ok ? number(row.beta_simple, 3, true) : '—'}</span>
    </button>`;
  }).join('');
}

export function renderInspector(host, edge, tables, provenance, mode) {
  if (!edge) { host.innerHTML = '<p class="note">Pick a line to see what supports it.</p>'; return; }
  const evidence = edge.evidence_id ? tables.evidence.find(row => row.evidence_id === edge.evidence_id) : null;
  const kind = { measured: 'Measured', cited: 'From a document', hypothesis: 'Your hypothesis' }[edge.kind];
  const measured = edge.kind === 'measured';
  host.innerHTML = `<p class="insp-kind ${edge.kind}"><i aria-hidden="true"></i>${kind}</p>
    <h3>${esc(nodeLabel(edge.from))} <span class="arrow" aria-hidden="true">→</span><span class="sr-only">to</span> ${esc(nodeLabel(edge.to))}</h3>
    ${finite(edge.beta) ? `<div class="insp-value">${number(edge.beta, 3, true)}</div><p class="insp-unit">${esc(edge.unit || 'Unit not supplied')}</p>${intervalPlot(edge.beta, edge.lo, edge.hi)}` : ''}
    <p>${esc(edge.note)}</p>
    <dl class="insp-facts">
      <div><dt>${measured ? '95% range' : 'Numbers'}</dt><dd>${measured ? interval(edge.lo, edge.hi) : 'Not estimated'}</dd></div>
      <div><dt>Method</dt><dd>${measured ? `OLS with constant, Newey–West HAC(4) · <code>${esc(edge.source)}</code> · p ${probability(edge.p)}` : esc(edge.source)}</dd></div>
      <div><dt>Sample</dt><dd>${finite(edge.n) ? `${number(edge.n, 0)} weeks` : 'Not supplied for this link'}</dd></div>
      <div><dt>Coverage</dt><dd>${edge.kind === 'hypothesis' ? 'Not applicable' : `${esc(provenance.coverage)} · ${esc(provenance.verified)}`}</dd></div>
      <div><dt>Document</dt><dd>${evidence ? esc(evidence.evidence_id) : 'None supplied'}</dd></div>
    </dl>
    ${evidence ? `<blockquote>${esc(evidence.excerpt)}</blockquote><a href="#evidence-section">Read the source →</a>` : '<a href="#evidence-section">See the evidence gap →</a>'}
    <p class="insp-caveat">${edge.kind === 'hypothesis' ? 'You added this dotted line. It is a question, not a finding.' : 'Association, not causation. Links measured in different units can’t be compared as weights.'}</p>
`;
}

function durationCheck(row) {
  if (!row || ![row.duration_years, row.yield_move_per_10pct_oil_bp, row.implied_move_pct, row.measured_move_pct].every(finite)) return '';
  return `<div class="duration-check"><h4>Duration cross-check</h4>
    <p class="note">If Brent rises 10%, yields have moved about ${number(row.yield_move_per_10pct_oil_bp, 1, true)} bp. With an effective duration of ${number(row.duration_years, 2)} years (issuer document in the data contract), that implies a ${percent(row.implied_move_pct)} price move.</p>
    <dl class="ledger"><div><dt>Implied by duration</dt><dd>${percent(row.implied_move_pct)}</dd></div><div><dt>Measured by the oil beta</dt><dd>${percent(row.measured_move_pct)}</dd></div></dl>
    <p class="note">Close numbers mean the rates channel can account for most of the measured move. It’s a consistency check, not proof of the mechanism.</p></div>`;
}

export function renderDecomposition(host, tables, ticker) {
  const chain = tables.chain_reconciliation.find(row => row.ticker === ticker);
  const duration = durationCheck(tables.duration_check?.find(row => row.ticker === ticker));
  const t = esc(shortTicker(ticker));
  if (isStock(ticker)) {
    host.innerHTML = `<div class="col-head"><h3>Attribution</h3><span class="tag">Single company</span></div>
      <p class="lead-p">${t} is one company, so there are no fund holdings to break down. Its oil beta is a property of the share price itself.</p>
      ${chain ? `<dl class="ledger"><div><dt>Measured total beta</dt><dd>${number(chain.beta_direct, 3, true)}</dd></div><div><dt>Product of chain coefficients</dt><dd>${number(chain.beta_chain, 3, true)}</dd></div><div><dt>Chain ÷ direct</dt><dd>${finite(chain.share_explained) ? number(chain.share_explained, 3) : 'Unavailable'}</dd></div></dl><p class="note">Chain tested: ${esc(chain.chain)}. The ratio can exceed 1 or go negative. It’s a cross-check, not a causal share.</p>`
        : `<dl class="ledger"><div><dt>Oil relationship</dt><dd>Measured</dd></div><div><dt>Transmission chain</dt><dd>Not supplied for ${t}</dd></div></dl>`}
      <p class="note">Why the price moves with oil (revenue, costs, rates or sentiment) needs documents, not just the beta.</p>`;
    return;
  }
  host.innerHTML = `<div class="col-head"><h3>Attribution</h3><span class="tag">Holdings breakdown unavailable</span></div>
    <p class="lead-p">We can’t say which holdings drive ${t}’s oil beta. There are no dated constituent weights joined to contribution statistics, and the persona portfolios in the contract belong to investors, not to this fund.</p>
    ${chain ? `<dl class="ledger">
      <div><dt>Measured total beta</dt><dd>${number(chain.beta_direct, 3, true)}</dd></div>
      <div><dt>Product of chain coefficients</dt><dd>${number(chain.beta_chain, 3, true)}</dd></div>
      <div><dt>Chain ÷ direct</dt><dd>${finite(chain.share_explained) ? number(chain.share_explained, 3) : 'Unavailable'}</dd></div>
    </dl><p class="note">Chain tested: ${esc(chain.chain)}. The ratio can exceed 1 or go negative. It’s a cross-check, not a causal share.</p>`
    : `<dl class="ledger">
      <div><dt>Oil relationship</dt><dd>Measured</dd></div>
      <div><dt>Constituent contributions</dt><dd>Not supplied</dd></div>
      <div><dt>Transmission chain</dt><dd>Not supplied for ${t}</dd></div>
    </dl>`}
    ${duration}
    <p class="note">Energy-sector weight is not oil beta, and XEG is not XIU’s energy sleeve. No proxy attribution is shown.</p>`;
}

export function renderScenario(host, tables, ticker, shock, mode) {
  const rows = tables.scenarios.filter(row => row.subject_type === 'ticker' && row.subject === ticker);
  const row = rows.find(item => item.shock_pct === shock);
  if (!row || ![row.impact_pct, row.lo_pct, row.hi_pct].every(finite) || row.lo_pct > row.impact_pct || row.impact_pct > row.hi_pct) {
    host.innerHTML = '<div class="empty"><strong>Scenario unavailable.</strong>No valid precomputed result was supplied for this ticker and shock. The browser doesn’t estimate missing results.</div>'; return;
  }
  const t = esc(shortTicker(ticker));
  const valid = rows.filter(item => [item.lo_pct, item.hi_pct].every(finite));
  const domain = [Math.min(0, ...valid.map(item => item.lo_pct)), Math.max(0, ...valid.map(item => item.hi_pct))];
  const scale = Math.max(Math.abs(shock), Math.abs(row.lo_pct), Math.abs(row.hi_pct)) || 1;
  const bar = (value, cls) => {
    const half = Math.max(Math.abs(value) / scale * 50, .4);
    return `<i class="bar ${cls} ${value < 0 ? 'neg' : 'pos'}" style="left:${value < 0 ? 50 - half : 50}%;width:${half}%"></i>`;
  };
  const sign = row.impact_pct < 0 ? 'neg' : 'pos';
  host.innerHTML = `<p class="shock-label">Estimated move in ${t} (CAD) if Brent moves ${percent(shock, 0)}</p>
    <div class="shock-number ${sign}">${counter('impact', row.impact_pct, 2, '%')}</div>
    <p class="shock-range">Range ${percent(row.lo_pct)} to ${percent(row.hi_pct)}</p>
    <div class="bars" role="img" aria-label="Brent ${percent(shock, 0)} compared with ${t} ${percent(row.impact_pct)} on the same scale">
      <div class="bar-row"><span>Brent</span><div class="bar-track">${bar(shock, 'oil')}</div><b>${percent(shock, 0)}</b></div>
      <div class="bar-row"><span>${t}</span><div class="bar-track">${bar(row.impact_pct, 'etf')}</div><b>${percent(row.impact_pct)}</b></div>
    </div>
    <p class="note">Both bars use the same scale.</p>
    <div class="shock-plot">${intervalPlot(row.impact_pct, row.lo_pct, row.hi_pct, { unit: '%', label: 'Transformed coefficient interval, not a prediction interval', domain })}</div>
    ${mode === 'preview' ? '<p class="note">Illustrative local scenario, computed from rounded notebook betas with the contract formula. Not an AWS result.</p>' : '<p class="note">Precomputed scenario from the configured backend.</p>'}`;
}

function documentMetadata(row) {
  // The evidence table has no title, issuer, publication date, or verification timestamp.
  // Never infer these from a ticker, URL, or document filename.
  const url = sourceURL(row?.source_url);
  return `<dl class="meta-grid">
    <div><dt>Original title</dt><dd>Not supplied</dd></div>
    <div><dt>Issuer</dt><dd>Not supplied</dd></div>
    <div><dt>Published</dt><dd>Not supplied</dd></div>
    <div><dt>Source link</dt><dd>Not independently verified</dd></div>
    <div><dt>Document type</dt><dd>${esc(row?.doc_type || 'Not supplied')}</dd></div>
    <div><dt>Section</dt><dd>${esc(row?.section || 'Not supplied')}</dd></div>
  </dl>${url ? `<p class="note"><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Open supplied source ↗</a> · unverified, opens a new tab</p>` : '<p class="note">No usable source link supplied.</p>'}`;
}

export function renderEvidence(host, counter, tables, ticker) {
  const evidence = tables.evidence.filter(row => row.ticker === ticker);
  counter.textContent = evidence.length ? `${evidence.length} passage${evidence.length === 1 ? '' : 's'} · unverified` : '0 documents supplied';
  if (!evidence.length) {
    host.innerHTML = `<div class="gap"><p class="lead-p">No documents supplied for ${esc(shortTicker(ticker))}. The statistics show how it moved with oil but not why.</p>${documentMetadata(null)}</div>`; return;
  }
  host.innerHTML = evidence.map(row => `<article class="doc">
    <p class="kicker">${esc(row.evidence_id)} · ${esc(row.channel)} · ${esc(row.direction)}</p>
    ${row.excerpt ? `<blockquote>${esc(row.excerpt)}</blockquote>` : '<p class="note">Passage unavailable.</p>'}
    ${documentMetadata(row)}
    <p class="note">The pipeline checks that the text is verbatim. That doesn’t verify the document or the mechanism.</p>
  </article>`).join('');
}

function rollingPlot(rows) {
  const valid = rows.filter(row => /^\d{4}-\d{2}-\d{2}$/.test(row.week) && finite(row.beta_52w)).sort((a, b) => a.week.localeCompare(b.week));
  if (valid.length < 2) return '<div class="empty"><strong>Rolling history unavailable.</strong>No complete 52-week rolling series was supplied, so no trend line is drawn.</div>';
  const values = valid.map(row => row.beta_52w);
  const min = Math.min(0, ...values), max = Math.max(0, ...values), extent = max - min || 1;
  const start = Date.parse(valid[0].week), end = Date.parse(valid.at(-1).week);
  const x = row => 20 + (Date.parse(row.week) - start) / (end - start || 1) * 420;
  const y = value => 145 - (value - min) / extent * 115;
  const path = valid.map((row, i) => `${i ? 'L' : 'M'}${x(row)},${y(row.beta_52w)}`).join(' ');
  return `<svg class="rolling-plot" viewBox="0 0 460 180" role="img" aria-label="52-week rolling oil beta, ${esc(valid[0].week)} to ${esc(valid.at(-1).week)}. Range ${number(min)} to ${number(max)}."><line class="zero" x1="20" x2="440" y1="${y(0)}" y2="${y(0)}"/><path d="${path}"/><text x="20" y="17">${number(max)} β</text><text x="440" y="155" text-anchor="end">${number(min)} β</text><text x="20" y="175">${esc(valid[0].week)}</text><text x="440" y="175" text-anchor="end">${esc(valid.at(-1).week)}</text></svg>`;
}

export function renderExpert(host, tables, row) {
  const controlled = row.market_ticker && row.market_ticker !== 'none';
  host.innerHTML = `<header class="section-head"><h2>Diagnostics</h2><p>OLS with Newey–West HAC(4) standard errors, weekly log returns.</p></header>
    <div class="expert-grid">
      <div><table><caption class="sr-only">Regression diagnostics for ${esc(row.ticker)}</caption><tbody>
        <tr><th scope="row">Simple beta</th><td>${number(row.beta_simple, 6)}</td></tr>
        <tr><th scope="row">p / adjusted q</th><td>${probability(row.p_simple)} / ${probability(row.q_simple)}</td></tr>
        <tr><th scope="row">Market control</th><td>${controlled ? esc(row.market_ticker) : 'None; simple values copied'}</td></tr>
        <tr><th scope="row">Adjusted beta / p</th><td>${number(row.beta_mkt)} / ${probability(row.p_mkt)}</td></tr>
        <tr><th scope="row">Adjusted 95% range</th><td>${interval(row.lo_mkt, row.hi_mkt)}</td></tr>
        <tr><th scope="row">Excluding 2022: beta / p</th><td>${number(row.beta_ex2022)} / ${probability(row.p_ex2022)}</td></tr>
        <tr><th scope="row">Excluding 2022: range</th><td>${interval(row.lo_ex2022, row.hi_ex2022)}</td></tr>
        <tr><th scope="row">Up / down oil beta</th><td>${number(row.beta_up)} / ${number(row.beta_down)}</td></tr>
        <tr><th scope="row">Incremental R²</th><td>${number(row.r2_incremental)}</td></tr>
      </tbody></table>
      <p class="note">Missing fields stay unavailable. A range that excludes zero doesn’t prove causality; adjusted q accounts for testing many tickers.</p></div>
      <div><h3>Does it persist?</h3>${rollingPlot(tables.rolling.filter(item => item.ticker === row.ticker))}
        <dl class="ledger"><div><dt>Out-of-sample direction hit rate</dt><dd>${finite(row.oos_hit_rate) ? `${number(row.oos_hit_rate * 100, 0)}%` : 'Unavailable'}</dd></div></dl>
        <p class="note">${finite(row.oos_n) ? number(row.oos_n, 0) : 'Unknown number of'} test weeks. Trained through 2024, tested from 2025 on the largest 10% of oil moves. Not general forecast accuracy.</p></div>
    </div>`;
}

export function previewExplanation(question, row, tables) {
  const text = question.toLowerCase();
  const t = shortTicker(row.ticker);
  const prefix = `${t} has a historical oil beta of ${number(row.beta_simple, 3, true)}, with a 95% range of ${interval(row.lo_simple, row.hi_simple)} across ${number(row.n_weeks, 0)} weeks. `;
  if (/evidence|source|document|why|where|explain|come from|pathway/.test(text)) {
    const chain = tables.chain_reconciliation.find(item => item.ticker === row.ticker);
    return prefix + (chain ? `The model tests one route: ${chain.chain}. That’s a statistical pathway, not a proven cause. ` : `No measured transmission chain is supplied for ${t}. `) + 'This local summary does not verify documents or holdings attribution. Inspect the supplied evidence and any gaps before attributing anything.';
  }
  if (/reliab|confiden|stable|risk|uncertain/.test(text)) return prefix + (row.lo_simple <= 0 && row.hi_simple >= 0 ? 'The range crosses zero, so the direction is uncertain. ' : 'The range excludes zero, but relationships drift. ') + `Leaving out 2022, p = ${probability(row.p_ex2022)}. Switch to Expert for the full diagnostics. This is history, not a prediction.`;
  return prefix + 'This local explanation gives a fixed summary of the supplied statistics; it can’t answer arbitrary questions. A connected backend is needed for that. Try the shock scenarios above in the meantime.';
}
