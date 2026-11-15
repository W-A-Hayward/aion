import { escapeHTML as esc, number, percent, interval, finite, shortTicker } from './formatters.js';
import { CORE_TICKERS, TICKER_INFO, SHOCKS } from './config.js';
import { PERSONAS, DEFAULT_NAME, MAX_SAVED, portfolioRows, contributions, weightedBeta, shockImpact } from './workspace-store.js';
import { intervalPlot } from './render.js';

const COLORS = ['#1f2937', '#2563eb', '#6b7280', '#93c5fd', '#0f766e', '#b45309', '#9ca3af', '#7c3aed'];
export const money = value => finite(value) ? new Intl.NumberFormat('en-CA', { style: 'currency', currency: 'CAD', maximumFractionDigits: 0 }).format(value) : 'Unavailable';
export const initials = name => name === DEFAULT_NAME ? '+' : name.split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]).join('').toUpperCase() || '+';
const info = ticker => TICKER_INFO[ticker] || { name: ticker, blurb: '', kind: 'etf' };

// One <option> list for every ticker picker: grouped ETFs / stocks, with names.
export function tickerOptions(selected, disabled = []) {
  const group = (label, kind) => `<optgroup label="${label}">${CORE_TICKERS.filter(t => info(t).kind === kind).map(t =>
    `<option value="${esc(t)}" ${t === selected ? 'selected' : ''} ${disabled.includes(t) && t !== selected ? 'disabled' : ''}>${esc(shortTicker(t))} · ${esc(info(t).name)}</option>`).join('')}</optgroup>`;
  return group('ETFs', 'etf') + group('Stocks', 'stock');
}

function portfolioPanel(data, workspace, shock) {
  if (!data) return '<div class="workspace-empty"><h3>Portfolio data unavailable.</h3><p>Your saved profile and notes are still here. The local snapshot could not be loaded.</p><button class="ghost-button" data-action="retry-data">Try again</button></div>';
  const custom = workspace.portfolio === 'custom', persona = PERSONAS[workspace.portfolio];
  const holdings = portfolioRows(data, workspace), rows = contributions(data, holdings);
  const summed = weightedBeta(data, holdings);
  const pb = custom ? null : data.portfolio_beta.find(row => row.persona === workspace.portfolio);
  const scenario = custom ? null : data.scenarios.find(row => row.subject === workspace.portfolio && row.subject_type === 'persona' && row.shock_pct === shock);
  const customImpact = custom ? shockImpact(summed, shock) : null;
  const maxContribution = Math.max(...rows.filter(row => finite(row.contribution)).map(row => Math.abs(row.contribution)), .001);
  const title = custom ? workspace.custom.name : `${persona.name}’s sample portfolio`;
  const alternatives = custom ? [] : data.alternatives.filter(row => row.persona === workspace.portfolio);
  const track = value => finite(value) ? `<span class="contribution-track" aria-hidden="true"><i style="width:${Math.abs(value) / maxContribution * 50}%;left:${value < 0 ? 50 - Math.abs(value) / maxContribution * 50 : 50}%"></i></span>` : '';

  return `<div class="persona-selector" role="group" aria-label="Choose a sample portfolio">${Object.entries(PERSONAS).map(([id, p]) => `<button type="button" class="persona-option" data-persona="${id}" aria-pressed="${workspace.portfolio === id}"><span class="persona-initial">${p.initials}</span><b>${p.name} · ${p.title}</b><small>${p.risk} risk · ${p.horizon} · ${p.experience.toLowerCase()} investor · fictional</small></button>`).join('')}</div>
  <div class="workspace-toolbar">${workspace.custom ? `<button type="button" class="ghost-button custom-pill" data-persona="custom" aria-pressed="${custom}">Custom: ${esc(workspace.custom.name)}</button>` : '<span></span>'}<button type="button" class="primary-button" data-action="build">New custom portfolio</button></div>
  <p class="snapshot-warning">Local preview only. Saved sample-portfolio results use the earlier weighted-log-return model. The current backend sums weighted simple returns, then takes the log. Updated portfolio estimates and ranges are unavailable here. Custom mixes and alternative comparisons are proxy estimates, not measured portfolio regressions.</p>
  <div class="portfolio-layout"><article class="workspace-panel card">
    <div class="workspace-panel-head"><div><span class="label">${custom ? 'Custom portfolio' : 'Sample portfolio · fictional'}</span><h2>${esc(title)}</h2><p>${custom ? 'Your weights. Hypothetical, not a real account.' : esc(persona.description)}</p></div><button type="button" class="ghost-button" data-action="edit-portfolio">${custom ? 'Edit allocation' : 'Customize a copy'}</button></div>
    <form id="capital-form" class="portfolio-capital"><label for="mock-capital">Illustrative capital · CAD</label><input id="mock-capital" name="capital" type="number" min="1" max="100000000" step="1" value="${workspace.capital}" required><button class="ghost-button" type="submit">Apply</button></form>
    <div class="allocation-strip" role="img" aria-label="${esc(holdings.map(row => `${row.ticker} ${number(row.weight * 100, 1)} percent`).join(', '))}">${holdings.map((row, i) => `<span style="width:${row.weight * 100}%;--slice:${COLORS[i % COLORS.length]}"></span>`).join('')}</div>
    <div class="holdings-table-wrap"><table class="holdings-table"><caption class="sr-only">Holdings and weighted oil-beta contributions</caption>
      <thead><tr><th scope="col">Holding</th><th scope="col">Weight</th><th scope="col">Mock allocation</th><th scope="col">Oil beta</th><th scope="col">Weight × beta</th></tr></thead>
      <tbody>${rows.map((row, i) => `<tr><td><span class="holding-name"><i class="holding-swatch" style="--slice:${COLORS[i % COLORS.length]}" aria-hidden="true"></i><button type="button" class="holding-link" data-open-ticker="${esc(row.ticker)}" title="Investigate ${esc(info(row.ticker).name)}">${esc(shortTicker(row.ticker))} ↗</button><small class="holding-blurb">${esc(info(row.ticker).name)}</small></span></td><td>${number(row.weight * 100, 1)}%</td><td>${money(row.weight * workspace.capital)}</td><td>${number(row.beta, 3, true)}</td><td class="contribution-cell">${number(row.contribution, 4, true)}${track(row.contribution)}</td></tr>`).join('')}</tbody>
      <tfoot><tr><th scope="row">Total</th><td>${number(holdings.reduce((s, r) => s + r.weight, 0) * 100, 1)}%</td><td>${money(workspace.capital)}</td><td></td><td class="contribution-cell"><b>${number(summed, 4, true)}</b></td></tr></tfoot>
    </table></div>
    <p class="note">Amounts use the illustrative capital above, not market prices. Weight × beta is a per-holding proxy contribution; its sum is not the current model’s measured portfolio beta.</p>
    <div class="portfolio-metrics">
      <div><dt>${custom ? 'Weighted-beta proxy' : 'Legacy portfolio beta · preview'}</dt><dd>${number(pb ? pb.beta : summed, 3, true)}</dd><small>${pb ? 'Saved regression using the earlier return formula' : 'Approximation: sum of weight × beta'}</small></div>
      <div><dt>Holdings / sample</dt><dd>${holdings.length} <small>/ ${number(pb ? pb.n_weeks : data.sensitivities[0]?.n_weeks, 0)} weeks</small></dd><small>Returns measured in CAD</small></div>
    </div>
    ${pb ? `${intervalPlot(pb.beta, pb.lo, pb.hi)}<p class="note">95% range ${interval(pb.lo, pb.hi)}, p ${number(pb.p, 3)}, from the saved legacy regression; not the updated backend method.</p>`
      : '<p class="note">No 95% range for a custom portfolio: that needs a regression on its own returns, which only the backend can run.</p>'}
  </article>
  <aside class="workspace-panel card"><h2 class="panel-title">Oil shock</h2><p class="note">Conditional statistical scenario, not a price prediction.</p>
    <div class="portfolio-shocks" role="group" aria-label="Brent shock">${SHOCKS.map(value => `<button type="button" data-portfolio-shock="${value}" aria-pressed="${value === shock}">${percent(value, 0)}</button>`).join('')}</div>
    ${scenario ? `<p class="label">${custom ? 'Illustrative proxy scenario' : 'Legacy saved scenario · preview'}</p><div class="portfolio-scenario ${scenario.impact_pct < 0 ? 'neg' : 'pos'}">${percent(scenario.impact_pct)}</div><p>${money(scenario.impact_pct / 100 * workspace.capital)} <span class="note">on ${money(workspace.capital)} of illustrative capital</span></p>${intervalPlot(scenario.impact_pct, scenario.lo_pct, scenario.hi_pct, { unit: '%', label: 'Conditional portfolio impact range' })}<p class="note">Range ${percent(scenario.lo_pct)} to ${percent(scenario.hi_pct)}. Saved notebook output.</p>`
      : finite(customImpact) ? `<p class="label">${custom ? 'Illustrative proxy scenario' : 'Legacy saved scenario · preview'}</p><div class="portfolio-scenario ${customImpact < 0 ? 'neg' : 'pos'}">${percent(customImpact)}</div><p>${money(customImpact / 100 * workspace.capital)} <span class="note">on ${money(workspace.capital)} of illustrative capital</span></p><p class="note">Proxy approximation from weighted β = ${number(summed, 4, true)}. No range without a portfolio regression.</p>`
      : '<div class="workspace-empty"><h3>No scenario available.</h3><p>A holding is missing its beta, so no impact can be computed.</p></div>'}
  </aside></div>
  ${alternatives.length ? `<section class="workspace-section"><h3>Alternatives</h3><p class="note">Swaps listed in the data contract, compared using weighted-beta proxies at a +30% Brent shock. These are not exact portfolio regressions or recommendations.</p><div class="alternatives-grid">${alternatives.map(row => `<article class="alternative-item"><h4>${esc(shortTicker(row.holding))} → ${esc(shortTicker(row.alternative))}</h4><p>${row.persona === 'amira' ? 'Move 25 points of weight' : 'Replace the holding at the same weight'} · beta ${number(row.beta_holding, 3, true)} → ${number(row.beta_alternative, 3, true)}</p><div class="alternative-compare"><span>${percent(row.impact30_before_pct)}<small> before</small></span><span>→ ${percent(row.impact30_after_pct)}<small> after</small></span></div><button type="button" class="ghost-button" data-alternative="${esc(row.holding)}" data-replacement="${esc(row.alternative)}">Use as custom portfolio</button></article>`).join('')}</div></section>` : ''}`;
}

function watchPanel(data, workspace) {
  const remaining = CORE_TICKERS.filter(t => !workspace.watchlist.includes(t));
  return `<div class="workspace-toolbar"><div><h2>Watchlist</h2><p class="note">No live prices.</p></div>${remaining.length ? `<form id="watch-add-form"><label class="sr-only" for="watch-add">Ticker to watch</label><select id="watch-add" name="ticker">${tickerOptions(remaining[0], workspace.watchlist)}</select> <button class="primary-button" type="submit">+ Add</button></form>` : '<span class="tag">Watching all 14 supported tickers</span>'}</div>
  ${workspace.watchlist.length ? `<div class="watch-grid">${workspace.watchlist.map(t => {
    const row = data?.sensitivities.find(r => r.ticker === t);
    const verdict = !row ? 'Estimate not loaded' : row.lo_simple <= 0 && row.hi_simple >= 0 ? 'Direction unclear · range crosses zero' : row.beta_simple < 0 ? 'Has tended to fall when oil rises' : 'Has tended to rise with oil';
    return `<article class="watch-card card"><header><div><span class="label">${esc(t)} · ${info(t).kind === 'stock' ? 'stock' : 'ETF'}</span><h3>${esc(shortTicker(t))}</h3><p class="note">${esc(info(t).name)}</p></div><button type="button" class="ghost-button" data-unwatch="${esc(t)}" aria-label="Remove ${esc(t)} from watchlist">×</button></header><p class="note">Historical oil beta</p><div class="watch-beta">${number(row?.beta_simple, 3, true)}</div><p>95% range: ${interval(row?.lo_simple, row?.hi_simple)}</p><p class="note">${verdict}</p><button type="button" class="ghost-button" data-open-ticker="${esc(t)}">Open</button></article>`;
  }).join('')}</div>` : '<div class="workspace-empty"><h3>Nothing on your watchlist</h3><p>Add a ticker above, or press Watch while researching one.</p></div>'}`;
}

function savedPanel(workspace) {
  return `<div class="workspace-toolbar"><div><h2>Saved research</h2><p class="note">${workspace.saved.length} of ${MAX_SAVED} entries.</p></div><button type="button" class="primary-button" data-action="research">Open research</button></div>
  ${workspace.saved.length ? `<div class="saved-grid">${workspace.saved.map(item => `<article class="saved-card card"><header><span class="tag">${esc(shortTicker(item.ticker))} · ${percent(item.shock, 0)} Brent</span><button type="button" class="ghost-button" data-delete-saved="${esc(item.id)}" aria-label="Delete ${esc(item.title)}">×</button></header><h3>${esc(item.title)}</h3><time datetime="${esc(item.savedAt)}">${esc(new Intl.DateTimeFormat('en-CA', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(item.savedAt)))}</time><p class="note">Saved beta ${number(item.beta, 3, true)} · 95% range ${interval(item.lo, item.hi)}</p><p class="note">${item.source === 'preview' ? 'Local preview' : 'Backend response, provenance not verified'}</p>${item.note ? `<p class="saved-note">${esc(item.note)}</p>` : '<p class="note">No note added.</p>'}<div class="buttons"><button type="button" class="ghost-button" data-open-saved="${esc(item.id)}">Open</button><button type="button" class="ghost-button" data-edit-note="${esc(item.id)}">Edit note</button></div></article>`).join('')}</div>`
    : '<div class="workspace-empty"><h3>No saved research</h3><p>Open a ticker in Research and press Save to keep its numbers with a note.</p></div>'}`;
}

export function renderWorkspace(host, { data, workspace, tab, shock, persistent, loading = false }) {
  const named = workspace.profile.name !== DEFAULT_NAME;
  host.innerHTML = `<header class="workspace-header"><div><h1 id="workspace-title">${named ? esc(workspace.profile.name) : 'Workspace'}</h1>
    <p class="note">${named ? `${esc(workspace.profile.goal)} · ` : ''}${persistent ? 'Stored in this browser only' : 'Browser storage unavailable; changes last this session only'} · no account or broker connection</p></div>
    <div class="buttons">${named ? '' : '<button type="button" class="primary-button" data-action="profile">Set up profile</button>'}</div></header>
  <div class="workspace-tabs" role="tablist" aria-label="Workspace sections">${[['portfolio', 'Portfolio', ''], ['watchlist', 'Watchlist', workspace.watchlist.length], ['saved', 'Saved', workspace.saved.length]].map(([id, label, count]) => `<button type="button" role="tab" id="tab-${id}" data-workspace-tab="${id}" aria-selected="${tab === id}" aria-controls="workspace-panel" tabindex="${tab === id ? 0 : -1}">${label}${count !== '' ? ` <small>${count}</small>` : ''}</button>`).join('')}</div>
  <div id="workspace-panel" role="tabpanel" aria-labelledby="tab-${tab}">${loading && tab !== 'saved' ? '<p class="note" role="status">Loading…</p>' : tab === 'portfolio' ? portfolioPanel(data, workspace, shock) : tab === 'watchlist' ? watchPanel(data, workspace) : savedPanel(workspace)}</div>
  <footer class="workspace-foot"><span class="note">${workspace.profile.experience === 'expert' ? 'Expert' : 'Plain-language'} explanations · returns in CAD</span><div class="buttons"><button type="button" class="ghost-button" data-action="profile">Edit profile</button><button type="button" class="ghost-button" data-action="export">Export</button><button type="button" class="ghost-button" data-action="import">Import</button><button type="button" class="ghost-button" data-action="reset">Reset</button></div></footer>`;
}
