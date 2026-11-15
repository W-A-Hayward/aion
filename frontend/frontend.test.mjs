import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { normalizeTables } from './api.js';
import { buildNetwork } from './graph.js';
import { finite, hasEstimate, number, sourceURL, escapeHTML } from './formatters.js';
import { renderEvidence, renderScenario, renderExpert } from './render.js';
import { CORE_TICKERS } from './config.js';
import { PERSONAS, validateHoldings, sanitizeWorkspace, splitEvenly, parseImport, weightedBeta, shockImpact } from './workspace-store.js';
import { renderWorkspace } from './workspace-render.js';
import { createAgentClient } from './agent-api.js';
import { renderAgentAnswer } from './agent-render.js';

const tables = normalizeTables(JSON.parse(await readFile(new URL('./preview-data.json', import.meta.url))));
const host = () => ({ innerHTML: '', textContent: '' });

test('zero is valid; null, absent, string and nonfinite values are not financial estimates', () => {
  assert.equal(finite(0), true);
  for (const value of [null, undefined, '', '0', NaN, Infinity]) assert.equal(finite(value), false);
  assert.equal(number(null), 'Unavailable');
  assert.equal(hasEstimate({ beta_simple: 0, lo_simple: -.1, hi_simple: .1, n_weeks: 261 }), true);
  assert.equal(hasEstimate({ beta_simple: 0, lo_simple: .1, hi_simple: -.1, n_weeks: 261 }), false);
});

test('API validation rejects malformed payloads instead of silently using preview data', () => {
  for (const payload of [null, [], {}, { sensitivities: {} }, { sensitivities: [null] }, { sensitivities: [], evidence: 'bad' }]) {
    assert.throws(() => normalizeTables(payload));
  }
  assert.deepEqual(normalizeTables({ sensitivities: [] }).evidence, []);
});

test('XIU default uses its captured beta and does not invent company or macro bridges', () => {
  const graph = buildNetwork(tables, 'XIU.TO');
  assert.equal(graph.edges[0].beta, .010571);
  assert.equal(graph.hasBridge, false);
  assert.equal(graph.edges.filter(edge => edge.to === 'XIU.TO').length, 1);
  assert.equal(graph.edges.some(edge => ['XOM', 'CNQ.TO', 'XEG.TO'].includes(edge.to)), false);
  assert.equal(graph.edges.some(edge => edge.kind === 'hypothesis'), false);
});

test('hypotheses require explicit user opt-in and contain no estimates', () => {
  const graph = buildNetwork(tables, 'XIU.TO', { macroContext: false, hypothesis: true });
  const hypothesis = graph.edges.find(edge => edge.kind === 'hypothesis');
  assert.equal(hypothesis.source, 'User exploration');
  assert.equal(hypothesis.beta, undefined);
  assert.ok(graph.factors.includes(hypothesis.from));
});

test('TLT network uses the supplied rates chain even with macro context hidden', () => {
  const graph = buildNetwork(tables, 'TLT', { macroContext: false });
  assert.equal(graph.hasBridge, true);
  assert.deepEqual(graph.factors, ['us10y']);
  assert.ok(graph.edges.some(edge => edge.from === 'us10y' && edge.to === 'TLT'));
});

test('ticker scenarios cover all 14 core tickers at contract shocks with ordered ranges', () => {
  const tickerRows = tables.scenarios.filter(row => row.subject_type === 'ticker');
  assert.equal(tickerRows.length, CORE_TICKERS.length * 4);
  for (const row of tickerRows) {
    assert.ok([-30, -15, 15, 30].includes(row.shock_pct));
    assert.ok(row.lo_pct <= row.impact_pct && row.impact_pct <= row.hi_pct);
    const sensitivity = tables.sensitivities.find(item => item.ticker === row.subject);
    assert.ok(Math.abs(row.impact_pct - shockImpact(sensitivity.beta_simple, row.shock_pct)) < 0.000001);
    const ends = [sensitivity.lo_simple, sensitivity.hi_simple].map(beta => shockImpact(beta, row.shock_pct));
    assert.ok(Math.abs(row.lo_pct - Math.min(...ends)) < 0.000001 && Math.abs(row.hi_pct - Math.max(...ends)) < 0.000001);
  }
  const element = host();
  renderScenario(element, tables, 'XIU.TO', 30, 'preview');
  assert.match(element.innerHTML, /Illustrative local scenario/);
  renderScenario(element, { scenarios: [] }, 'XIU.TO', 30, 'api');
  assert.match(element.innerHTML, /Scenario unavailable/);
  assert.doesNotMatch(element.innerHTML, /0\.28/);
});

test('snapshot matches the data contract: 14 core tickers, persona weights, alternatives', () => {
  assert.deepEqual(tables.sensitivities.map(row => row.ticker), [...CORE_TICKERS]);
  assert.ok(tables.sensitivities.every(row => hasEstimate(row) && row.universe === 'core' && row.n_weeks === 261));
  const contract = { robert: { TLT: .3, 'XBB.TO': .4, 'ENB.TO': .15, 'RY.TO': .15 }, amira: { QQQ: .5, 'SHOP.TO': .25, 'XIU.TO': .25 }, mateo: { 'XIU.TO': .5, 'VFV.TO': .5 } };
  for (const [persona, weights] of Object.entries(contract)) {
    const rows = tables.persona_holdings.filter(row => row.persona === persona);
    assert.deepEqual(Object.fromEntries(rows.map(row => [row.ticker, row.weight])), weights);
    assert.ok(Object.hasOwn(PERSONAS, persona));
  }
  assert.deepEqual(tables.alternatives.map(row => `${row.persona}:${row.holding}>${row.alternative}`),
    ['robert:TLT>ZST.TO', 'robert:XBB.TO>ZST.TO', 'mateo:XIU.TO>XESG.TO', 'mateo:VFV.TO>XSP.TO', 'amira:QQQ>XIU.TO']);
  assert.deepEqual(tables.duration_check.map(row => [row.ticker, row.duration_years]), [['TLT', 14.63], ['XBB.TO', 6.72]]);
});

test('legacy snapshot and alternatives are internally consistent, not proof of the updated portfolio model', () => {
  for (const pb of tables.portfolio_beta) {
    const holdings = tables.persona_holdings.filter(row => row.persona === pb.persona);
    assert.ok(Math.abs(weightedBeta(tables, holdings) - pb.beta) < 0.000005, pb.persona);
    for (const row of tables.scenarios.filter(item => item.subject === pb.persona)) {
      assert.equal(row.subject_type, 'persona');
      assert.ok(Math.abs(row.impact_pct - shockImpact(pb.beta, row.shock_pct)) < 0.0001); // pb.beta is saved at 6 dp
    }
  }
  for (const alt of tables.alternatives) {
    const holdings = tables.persona_holdings.filter(row => row.persona === alt.persona).map(({ ticker, weight }) => ({ ticker, weight }));
    const original = holdings.find(row => row.ticker === alt.holding);
    const moved = alt.persona === 'amira' ? .25 : original.weight;
    original.weight -= moved;
    const existing = holdings.find(row => row.ticker === alt.alternative);
    if (existing) existing.weight += moved; else holdings.push({ ticker: alt.alternative, weight: moved });
    assert.ok(Math.abs(shockImpact(weightedBeta(tables, holdings), 30) - alt.impact30_after_pct) < 0.00001, `${alt.persona} ${alt.holding}`);
  }
});

test('obsolete ZST and XRB chains are absent; new Canada 2Y links can be rendered', () => {
  assert.ok(!tables.links.some(row => row.link_id === 'ca10y>ZST.TO'));
  assert.ok(!tables.chain_reconciliation.some(row => ['ZST.TO', 'XRB.TO'].includes(row.ticker)));
  assert.equal(buildNetwork(tables, 'ZST.TO', { macroContext: false }).hasBridge, false);
  const synthetic = { ...tables, links: [
    { link_id: 'oil>ca2y', from_node: 'oil', to_node: 'ca2y', beta: .5, lo: .1, hi: .9 },
    { link_id: 'ca2y>ZST.TO', from_node: 'ca2y', to_node: 'ZST.TO', beta: -.01, lo: -.02, hi: 0 },
  ] };
  const graph = buildNetwork(synthetic, 'ZST.TO', { macroContext: false });
  assert.deepEqual(graph.factors, ['ca2y']);
  assert.equal(graph.hasBridge, true);
});

test('portfolio UI distinguishes legacy results from weighted-beta proxy approximations', () => {
  const element = host();
  renderWorkspace(element, { data: tables, workspace: sanitizeWorkspace({ version: 1 }), tab: 'portfolio', shock: 30, persistent: true });
  assert.match(element.innerHTML, /Legacy portfolio beta/);
  assert.match(element.innerHTML, /not the current model’s measured portfolio beta/);
  assert.doesNotMatch(element.innerHTML, /exact oil beta|sums to the portfolio’s oil beta/);
});

const jobId = '12345678-1234-1234-1234-123456789abc';
const settings = { submitUrl: 'https://api.example.test/submit', statusUrl: 'https://api.example.test/status/{id}', timeoutMs: 100, jobTimeoutMs: 300, pollIntervalMs: 1 };
const questionArgs = { question: 'Investigate XIU.TO', persona: 'robert', level: 'beginner' };
const reply = data => ({ ok: true, json: async () => data });

test('chat submits the implemented contract once, polls pending/running and returns evidence', async () => {
  const requests = [], progress = [], queue = [
    { jobId, sessionId: 'session-1' }, { jobId, status: 'PENDING' }, { jobId, status: 'RUNNING' },
    { jobId, status: 'DONE', answer: 'Test answer', citations: [{ text: 'Synthetic passage' }], toolCalls: [], durationMs: 4 },
  ];
  const ask = createAgentClient(settings, async (url, options) => { requests.push({ url, options }); return reply(queue.shift()); }, async () => {});
  const result = await ask({ ...questionArgs, sessionId: 'session-1', onProgress: item => progress.push(item.status) });
  assert.deepEqual(JSON.parse(requests[0].options.body), { ...questionArgs, sessionId: 'session-1' });
  assert.equal(requests.filter(item => item.options.method === 'POST').length, 1);
  assert.equal(requests[1].url, `https://api.example.test/status/${jobId}`);
  assert.deepEqual(progress, ['SUBMITTING', 'PENDING', 'PENDING', 'RUNNING', 'DONE']);
  assert.equal(result.sessionId, 'session-1');
  assert.equal(result.citations[0].text, 'Synthetic passage');
  assert.ok(requests.every(item => item.options.credentials === 'omit'));
});

test('unconfigured chat, invalid personas and invalid status templates send no requests', async () => {
  let sent = 0;
  const transport = async () => { sent++; };
  await assert.rejects(createAgentClient({ ...settings, submitUrl: null }, transport)(questionArgs), /not configured/);
  await assert.rejects(createAgentClient(settings, transport)({ ...questionArgs, persona: 'custom' }), /custom portfolios/);
  await assert.rejects(createAgentClient({ ...settings, statusUrl: 'https://example.test/status' }, transport)(questionArgs), /contain/);
  await assert.rejects(createAgentClient(settings, transport)({ ...questionArgs, sessionId: 'bad session' }), /Invalid conversation/);
  assert.equal(sent, 0);
});

test('chat exposes failed, malformed and HTTP-error results without a preview fallback', async () => {
  for (const result of [
    { jobId, status: 'FAILED', error: 'Worker failed' },
    { jobId, status: 'DONE', answer: '' },
    { jobId: 'wrong', status: 'DONE', answer: 'wrong job' },
    { jobId, status: 'UNKNOWN' },
    { jobId, status: 'DONE', answer: 'x', citations: [null] },
  ]) {
    const queue = [{ jobId, sessionId: 'session-1' }, result];
    await assert.rejects(createAgentClient(settings, async () => reply(queue.shift()))(questionArgs));
  }
  let count = 0;
  await assert.rejects(createAgentClient(settings, async () => { count++; return { ok: false, status: 503 }; })(questionArgs), /503/);
  assert.equal(count, 1);
});

test('chat polling stops when cancelled and does not submit again', async () => {
  const controller = new AbortController(); let count = 0;
  const ask = createAgentClient(settings, async () => reply(++count === 1 ? { jobId, sessionId: 's' } : { jobId, status: 'RUNNING' }), async () => { controller.abort(); });
  await assert.rejects(ask({ ...questionArgs, signal: controller.signal }), { name: 'AbortError' });
  assert.equal(count, 2);
});

test('chat has a total waiting deadline, even while jobs keep reporting pending', async () => {
  let count = 0;
  const ask = createAgentClient({ ...settings, jobTimeoutMs: 10, pollIntervalMs: 5 }, async () => reply(++count === 1 ? { jobId, sessionId: 's' } : { jobId, status: 'PENDING' }));
  // Keep the test process alive while AbortSignal's unref'd deadline timer fires.
  const keeper = setTimeout(() => {}, 100);
  try { await assert.rejects(ask(questionArgs), { name: 'TimeoutError' }); }
  finally { clearTimeout(keeper); }
});

test('agent citations escape markup, reject unsafe links and disclose missing metadata', () => {
  const element = host();
  renderAgentAnswer(element, { jobId, answer: '<script>bad()</script>',
    citations: [{ text: '<img src=x>', source_url: 'javascript:alert(1)' }, { text: 'Synthetic', source_url: 's3://bucket/private' }],
    toolCalls: [{ name: '<b>tool</b>', input: { ticker: 'XIU.TO' }, output: '<script>bad()</script>[truncated]' }],
  }, { persona: 'robert', level: 'expert', ticker: 'XIU.TO' });
  assert.doesNotMatch(element.innerHTML, /<script>|<img|href="javascript:|href="s3:/);
  assert.match(element.innerHTML, /publication date: not supplied/);
  assert.match(element.innerHTML, /No public source link/);
  assert.match(element.innerHTML, /\[truncated\]/);
});

test('portfolios, watchlists and saved research only accept the 14 supported tickers', () => {
  assert.equal(validateHoldings([{ ticker: 'XIU.TO', weight: .5 }, { ticker: 'ENB.TO', weight: .5 }]), null);
  for (const ticker of ['AAPL', 'XEG.TO', 'BTC-USD', 'xiu.to', '', undefined]) {
    assert.match(validateHoldings([{ ticker, weight: 1 }]), /isn’t supported/);
  }
  assert.match(validateHoldings([{ ticker: 'TLT', weight: .5 }, { ticker: 'TLT', weight: .5 }]), /only once/);
  assert.match(validateHoldings([{ ticker: 'TLT', weight: .6 }, { ticker: 'SPY', weight: .3 }]), /add up to 100%. They add up to 90.00%/);
  assert.match(validateHoldings([{ ticker: 'TLT', weight: 0 }, { ticker: 'SPY', weight: 1 }]), /more than 0%/);
  const weights = splitEvenly(3);
  assert.deepEqual(weights, [.3334, .3333, .3333]);
  assert.equal(validateHoldings(['XIU.TO', 'TLT', 'SPY'].map((ticker, i) => ({ ticker, weight: weights[i] }))), null);
  for (const n of [1, 6, 7, 14]) assert.ok(Math.abs(splitEvenly(n).reduce((a, b) => a + b, 0) - 1) < 1e-9);
  const clean = sanitizeWorkspace({ version: 1, profile: { name: '<b>Lee</b>' }, watchlist: ['ENB.TO', 'AAPL', 'ENB.TO'],
    custom: { name: 'x', holdings: [{ ticker: 'AAPL', weight: 1 }] }, portfolio: 'custom',
    saved: [{ id: 'a', ticker: 'NVDA', shock: 30, source: 'preview', savedAt: '2026-11-14T00:00:00Z' }, { id: 'b', ticker: 'RY.TO', shock: 15, source: 'preview', savedAt: '2026-11-14T00:00:00Z' }] });
  assert.deepEqual(clean.watchlist, ['ENB.TO']);
  assert.equal(clean.custom, null);
  assert.equal(clean.portfolio, 'robert');
  assert.deepEqual(clean.saved.map(item => item.ticker), ['RY.TO']);
  assert.equal(clean.profile.name, '<b>Lee</b>'); // stored as text; every render escapes it
});

test('workspace import rejects foreign files and reports skipped entries', () => {
  assert.match(parseImport('not json').error, /valid JSON/);
  assert.match(parseImport('{"version":2}').error, /isn’t a Cascade/);
  const result = parseImport(JSON.stringify({ version: 1, profile: { name: 'Sam' }, watchlist: ['TLT', 'TSLA'] }));
  assert.equal(result.workspace.profile.name, 'Sam');
  assert.deepEqual(result.workspace.watchlist, ['TLT']);
  assert.equal(result.dropped, true);
});

test('workspace HTML escapes profile and portfolio names', () => {
  const element = host();
  const workspace = { ...sanitizeWorkspace({ version: 1, profile: { name: '<img src=x onerror=alert(1)>' }, portfolio: 'custom',
    custom: { name: '<script>x</script>', holdings: [{ ticker: 'XOM', weight: 1 }] } }) };
  renderWorkspace(element, { data: tables, workspace, tab: 'portfolio', shock: 30, persistent: true });
  assert.doesNotMatch(element.innerHTML, /<img src=x|<script>x/);
  assert.match(element.innerHTML, /No range without a portfolio regression/);
  assert.match(element.innerHTML, /\+0\.3574/); // XOM-only mix: beta equals XOM's own beta
});

test('evidence is empty in preview and backend text/URLs cannot execute markup', () => {
  assert.deepEqual(tables.evidence, []);
  assert.equal(sourceURL('javascript:alert(1)'), null);
  assert.equal(sourceURL('data:text/html,hello'), null);
  assert.equal(sourceURL('https://user:password@example.com'), null);
  assert.equal(sourceURL('https://example.com/report'), 'https://example.com/report');
  assert.equal(escapeHTML('<img onerror="x">'), '&lt;img onerror=&quot;x&quot;&gt;');
  const element = host(), counter = host();
  renderEvidence(element, counter, { evidence: [{ ticker: 'XIU.TO', excerpt: '<script>alert(1)</script>', source_url: 'javascript:alert(1)' }] }, 'XIU.TO');
  assert.doesNotMatch(element.innerHTML, /<script>|href="javascript:/);
  assert.match(element.innerHTML, /Not independently verified/);
  assert.match(element.innerHTML, /Original title/);
});

test('missing rolling history remains unavailable instead of a decorative trend', () => {
  const element = host();
  renderExpert(element, tables, tables.sensitivities[0]);
  assert.match(element.innerHTML, /Rolling history unavailable/);
  assert.doesNotMatch(element.innerHTML, /class="rolling-plot"/);
});

test('chat requests carry this browser\'s session token; it is created once and reused', async () => {
  const { sessionToken, SESSION_TOKEN_KEY } = await import('./agent-api.js');
  const store = new Map();
  const storage = { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  const first = sessionToken(storage);
  assert.match(first, /^[A-Za-z0-9_-]{43}$/);
  assert.equal(store.get(SESSION_TOKEN_KEY), first);
  assert.equal(sessionToken(storage), first);
  const settings = { submitUrl: 'https://api.example.test/jobs', statusUrl: 'https://api.example.test/jobs/{id}', timeoutMs: 1000, pollIntervalMs: 1, jobTimeoutMs: 5000 };
  const jobId = '11111111-1111-4111-8111-111111111111';
  const seen = [];
  const replies = [{ jobId, sessionId: 's1' }, { jobId, status: 'DONE', answer: 'ok' }];
  const ask = createAgentClient(settings, async (url, options) => { seen.push(options.headers['X-Cascade-Session']); return { ok: true, status: 200, json: async () => replies.shift() }; }, async () => {}, () => 'k'.repeat(40));
  await ask({ question: 'q', persona: 'robert', level: 'beginner' });
  assert.deepEqual(seen, ['k'.repeat(40), 'k'.repeat(40)]);
  const limited = createAgentClient(settings, async () => ({ ok: false, status: 429 }), async () => {}, () => 'k'.repeat(40));
  await assert.rejects(limited({ question: 'q', persona: 'robert', level: 'beginner' }), /Too many questions/);
});
