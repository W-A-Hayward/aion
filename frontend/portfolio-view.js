// "My portfolio" (from the account menu): the current portfolio, the profile, and saved portfolios the user can
// switch between. Saved portfolios live in the workspace, so they sync with the account like everything else.
import { TICKER_INFO } from './config.js';
import { escapeHTML as esc, shortTicker } from './formatters.js';
import { PERSONAS, PERSONA_HOLDINGS, MAX_PORTFOLIOS, portfolioRows } from './workspace-store.js';

const COLORS = ['#1f5f8b', '#2f8fa7', '#5fb2c4', '#94a3b8', '#cbd5e1', '#64748b'];
const money = v => `$${Math.round(v).toLocaleString('en-CA')}`;
export const currentName = ws => (ws.portfolio === 'custom' ? ws.custom?.name || 'My portfolio' : `${PERSONAS[ws.portfolio]?.name ?? 'Sample'}’s sample`);
export const currentHoldings = ws => portfolioRows(null, ws).map(({ ticker, weight }) => ({ ticker, weight }));

/** A saved copy of the current portfolio. */
export function snapshotPortfolio(ws, name, now = new Date()) {
  return { id: `pf-${now.getTime().toString(36)}-${Math.random().toString(36).slice(2, 6)}`, name: (name || currentName(ws)).trim().slice(0, 60),
    holdings: currentHoldings(ws), capital: ws.capital, savedAt: now.toISOString() };
}

const bars = holdings => `<div class="pf-bars" aria-hidden="true">${holdings.map((h, i) => `<i style="flex:${h.weight};background:${COLORS[i % COLORS.length]}"></i>`).join('')}</div>`;

export function renderPortfolioPage(ws, account = null) {
  const holdings = currentHoldings(ws);
  const saved = ws.portfolios ?? [];
  const sample = ws.portfolio !== 'custom' ? PERSONAS[ws.portfolio] : null;
  return `<header class="page-head">
      <p class="eyebrow-text">${account ? `Signed in as ${esc(account)}` : 'Saved in this browser'}</p>
      <h1 id="pf-title">My portfolio</h1>
      <p class="lede">The portfolio the agent analyses, your profile, and the portfolios you saved.</p>
    </header>
    <section class="pf-card" aria-labelledby="pf-current">
      <div class="pf-head"><div><p class="eyebrow-text">In use</p><h2 id="pf-current">${esc(currentName(ws))}</h2>${sample ? `<p class="fine">${esc(sample.title)} · ${esc(sample.description)}</p>` : ''}</div>
        <div class="page-actions"><button type="button" class="btn ghost sm" data-pf="edit">Edit</button><button type="button" class="btn ghost sm" data-pf="save">Save a copy</button><button type="button" class="btn primary sm" data-pf="ask">Ask about it</button></div></div>
      ${bars(holdings)}
      <div class="tbl"><table><thead><tr><th>Holding</th><th>Weight</th><th>Amount</th></tr></thead><tbody>
        ${holdings.map((h, i) => `<tr><td><span class="pf-sw" style="background:${COLORS[i % COLORS.length]}"></span>${esc(shortTicker(h.ticker))} <span class="pf-name">${esc(TICKER_INFO[h.ticker]?.name ?? '')}</span></td><td>${(h.weight * 100).toFixed(1).replace(/\.0$/, '')}%</td><td>${money(ws.capital * h.weight)}</td></tr>`).join('')}
      </tbody><tfoot><tr><th>Total</th><td>100%</td><td>${money(ws.capital)}</td></tr></tfoot></table></div>
    </section>
    <section class="pf-card" aria-labelledby="pf-saved-title">
      <div class="pf-head"><div><h2 id="pf-saved-title">Saved portfolios</h2><p class="fine">${saved.length ? `${saved.length} of ${MAX_PORTFOLIOS}` : 'Save a copy of a portfolio to come back to it later or compare.'}</p></div></div>
      ${saved.length ? `<ul class="pf-list">${saved.map(p => `<li>
          <div class="pf-li-main"><b>${esc(p.name)}</b><span>${p.holdings.map(h => `${esc(shortTicker(h.ticker))} ${Math.round(h.weight * 100)}%`).join(' · ')}</span><small>Saved ${esc(new Date(p.savedAt).toLocaleDateString('en-CA', { year: 'numeric', month: 'short', day: 'numeric' }))}</small></div>
          ${bars(p.holdings)}
          <div class="pf-li-actions"><button type="button" class="btn primary sm" data-pf="use" data-id="${esc(p.id)}">Use</button><button type="button" class="btn ghost sm" data-pf="delete" data-id="${esc(p.id)}" aria-label="Delete ${esc(p.name)}">Delete</button></div>
        </li>`).join('')}</ul>` : '<p class="pf-empty">No saved portfolios yet.</p>'}
    </section>
    <section class="pf-card" aria-labelledby="pf-profile-title">
      <div class="pf-head"><div><h2 id="pf-profile-title">Profile</h2></div><button type="button" class="btn ghost sm" data-pf="profile">Edit profile</button></div>
      <dl class="pf-dl"><div><dt>Name</dt><dd>${esc(ws.profile.name)}</dd></div><div><dt>Explanations</dt><dd>${ws.profile.experience === 'expert' ? 'Expert, statistics included' : 'Beginner, plain language'}</dd></div><div><dt>Goal</dt><dd>${esc(ws.profile.goal)}</dd></div></dl>
    </section>`;
}

/** Apply a saved portfolio: it becomes the custom portfolio in use. */
export function useSaved(ws, id) {
  const p = (ws.portfolios ?? []).find(x => x.id === id);
  if (!p) return null;
  const sample = Object.entries(PERSONA_HOLDINGS).find(([, hs]) => hs.length === p.holdings.length && hs.every(h => p.holdings.some(x => x.ticker === h.ticker && Math.abs(x.weight - h.weight) < 1e-9)));
  if (sample && p.name === `${PERSONAS[sample[0]].name}’s sample`) { ws.portfolio = sample[0]; }
  else { ws.portfolio = 'custom'; ws.custom = { name: p.name, holdings: p.holdings.map(h => ({ ...h })) }; }
  if (p.capital) ws.capital = p.capital;
  return ws;
}
