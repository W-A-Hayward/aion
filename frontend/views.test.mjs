import test from 'node:test';
import assert from 'node:assert/strict';
import { loadInvestigation, statisticsConfigured } from './api.js';
import { betaRanking, tickerDetail } from './stats-view.js';
import { renderPortfolioPage, snapshotPortfolio, useSaved, currentHoldings } from './portfolio-view.js';
import { sanitizeWorkspace, defaults, PERSONA_HOLDINGS } from './workspace-store.js';
import { VIEWS } from './views.js';

const settings = { investigationUrl: 'https://api.test/research', timeoutMs: 1000 };
const json = (d, status = 200) => ({ ok: status < 400, status, json: async () => d });
const SENS = [
  { ticker: 'XIU.TO', beta_simple: 0.011, lo_simple: -0.032, hi_simple: 0.054, p_simple: 0.6, q_simple: 0.8, n_weeks: 261, beta_mkt: 0.002, lo_mkt: -0.01, hi_mkt: 0.014, beta_ex2022: 0.02, p_ex2022: 0.5, oos_hit_rate: 0.3, oos_n: 10, beta_up: 0.01, beta_down: 0.02 },
  { ticker: 'XOM', beta_simple: 0.357, lo_simple: 0.3, hi_simple: 0.41, p_simple: 0.0001, n_weeks: 261 },
  { ticker: 'TLT', beta_simple: -0.089, lo_simple: -0.126, hi_simple: -0.053, p_simple: 0.001, n_weeks: 261 },
];
const ENVELOPE = { sensitivities: SENS, confidence: [{ ticker: 'XIU.TO', label: 'grey', reason_text: 'Not reliably linked.' }],
  scenarios: [{ subject: 'XIU.TO', subject_type: 'ticker', shock_pct: -30, impact_pct: -0.39, lo_pct: -1.9, hi_pct: 1.2 }, { subject: 'XIU.TO', subject_type: 'ticker', shock_pct: 30, impact_pct: 0.29, lo_pct: -0.8, hi_pct: 1.4 }],
  rolling: [{ ticker: 'XIU.TO', week: '2025-01-03', beta_52w: 0.05 }, { ticker: 'XIU.TO', week: '2026-11-13', beta_52w: -0.01 }],
  chain_reconciliation: [], evidence: [{ ticker: 'XIU.TO', excerpt: '<b>excerpt</b>', section: 'MD&A', source_url: 'javascript:alert(1)' }],
  meta: { as_of: '2026-11-13', missing: ['links'] } };

test('statistics come only from the backend research API', async () => {
  const seen = [];
  const { tables, meta } = await loadInvestigation({ ticker: 'XIU.TO', settings, transport: async (url, o) => { seen.push([String(url), o.credentials]); return json(ENVELOPE); } });
  assert.deepEqual(seen, [['https://api.test/research?ticker=XIU.TO', 'omit']]);
  assert.equal(tables.sensitivities.length, 3);
  assert.equal(meta.as_of, '2026-11-13');
  assert.equal(statisticsConfigured({ investigationUrl: null }), false);
  await assert.rejects(loadInvestigation({ ticker: 'XIU.TO', settings: { investigationUrl: null } }), /not configured/);
});

test('an undeployed or failing API is explained, never replaced by local data', async () => {
  await assert.rejects(loadInvestigation({ ticker: 'XIU.TO', settings, transport: async () => json({ message: 'Not Found' }, 404) }), /not deployed yet/);
  await assert.rejects(loadInvestigation({ ticker: 'XIU.TO', settings, transport: async () => json({ error: 'unknown ticker' }, 400) }), /answered: unknown ticker/);
  await assert.rejects(loadInvestigation({ ticker: 'XIU.TO', settings, transport: async () => { throw new TypeError('Failed to fetch'); } }), /Couldn’t reach/);
  await assert.rejects(loadInvestigation({ ticker: 'XIU.TO', settings, transport: async () => json({ nope: 1 }) }), /sensitivities/);
});

test('beta ranking: sorted, shared scale, selected ticker marked', () => {
  const html = betaRanking(SENS, 'TLT');
  assert.deepEqual([...html.matchAll(/data-stats-ticker="([^"]+)"/g)].map(m => m[1]), ['XOM', 'XIU.TO', 'TLT']);
  assert.match(html, /data-stats-ticker="TLT" aria-current="true"/);
  assert.match(html, /rank-dot neg/);
});

test('ticker detail shows backend figures and escapes backend text', () => {
  const html = tickerDetail({ ...ENVELOPE, links: [], edges: [], duration_check: [], persona_holdings: [], portfolio_exposure: [], portfolio_beta: [], alternatives: [] }, 'XIU.TO', ENVELOPE.meta);
  assert.match(html, /\+0\.011/);
  assert.match(html, /95% range -0\.032 to \+0\.054/);
  assert.match(html, /it had no settled direction/);
  assert.match(html, /3 of 10 big-move weeks/);
  assert.match(html, /Brent -30%/);
  assert.match(html, /<svg/, 'rolling beta chart');
  assert.match(html, /data to 2026-11-13/);
  assert.match(html, /Not available in this response: links/);
  assert.doesNotMatch(html, /<b>excerpt<\/b>|javascript:/);
  assert.match(tickerDetail({ sensitivities: [], confidence: [], scenarios: [], rolling: [], chain_reconciliation: [], evidence: [] }, 'QQQ'), /returned no estimate for QQQ/);
});

test('saved portfolios: snapshot, sanitize, use and escape', () => {
  const ws = sanitizeWorkspace({ ...defaults(), portfolio: 'amira', capital: 20000 });
  assert.deepEqual(currentHoldings(ws), PERSONA_HOLDINGS.amira.map(h => ({ ...h })));
  const copy = snapshotPortfolio(ws, 'Growth <b>test</b>', new Date('2026-11-16T10:00:00Z'));
  const withSaved = sanitizeWorkspace({ ...ws, portfolios: [copy, { id: 'bad', holdings: [{ ticker: 'BTC', weight: 1 }], savedAt: '2026-01-01' }] });
  assert.equal(withSaved.portfolios.length, 1, 'invalid saved portfolios are dropped');
  assert.equal(withSaved.portfolios[0].capital, 20000);
  const html = renderPortfolioPage(withSaved, 'robin');
  assert.match(html, /Signed in as robin/);
  assert.match(html, /Growth &lt;b&gt;test&lt;\/b&gt;/);
  assert.doesNotMatch(html, /<b>test<\/b>/);
  assert.match(html, /QQQ 50% · SHOP 25% · XIU 25%/);
  assert.match(html, /\$10,000/, 'amounts follow the capital');
  const switched = useSaved(sanitizeWorkspace({ ...withSaved, portfolio: 'robert' }), copy.id);
  assert.equal(switched.portfolio, 'custom');
  assert.equal(switched.custom.name, 'Growth <b>test</b>');
  assert.equal(useSaved(withSaved, 'missing'), null);
  assert.match(renderPortfolioPage(defaults(), null), /Saved in this browser[\s\S]*No saved portfolios yet/);
});

test('the app has exactly these views; evidence desk and local statistics are gone', async () => {
  assert.deepEqual([...VIEWS], ['agent', 'statistics', 'sources', 'about', 'portfolio']);
  const { readFile, access } = await import('node:fs/promises');
  const html = await readFile(new URL('./index.html', import.meta.url), 'utf8');
  for (const v of VIEWS) assert.match(html, new RegExp(`data-view="${v}"`));
  assert.doesNotMatch(html, /explorer\.html|evidence-desk|Evidence desk/);
  assert.doesNotMatch(html, /35 passages/, 'no counts at the top of the disclosures');
  for (const gone of ['preview-data.json', 'evidence-desk.js', 'app.js', 'render.js']) await assert.rejects(access(new URL(`./${gone}`, import.meta.url)), gone);
  const redirect = await readFile(new URL('./explorer.html', import.meta.url), 'utf8');
  assert.match(redirect, /evidence: 'sources'/);
});
