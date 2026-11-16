import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { normalizeTables } from './api.js';
import { finite, hasEstimate, number, sourceURL, escapeHTML } from './formatters.js';
import { CORE_TICKERS } from './config.js';
import { PERSONAS, validateHoldings, sanitizeWorkspace, splitEvenly, parseImport, weightedBeta, shockImpact } from './workspace-store.js';
import { createAgentClient } from './agent-api.js';

const host = () => ({ innerHTML: '', textContent: '' });
const jobId = '12345678-1234-1234-1234-123456789abc';
const settings = { submitUrl: 'https://api.example.test/submit', statusUrl: 'https://api.example.test/status/{id}', timeoutMs: 100, jobTimeoutMs: 300, pollIntervalMs: 1 };
const questionArgs = { question: 'Investigate XIU.TO', persona: 'robert', level: 'beginner' };
const reply = data => ({ ok: true, json: async () => data });

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
  await assert.rejects(createAgentClient(settings, transport)({ ...questionArgs, persona: 'bob' }), /Choose Robert, Amira, Mateo/);
  await assert.rejects(createAgentClient(settings, transport)({ ...questionArgs, persona: 'custom' }), /1–14 supported tickers/);
  await assert.rejects(createAgentClient(settings, transport)({ ...questionArgs, persona: 'custom', holdings: [{ ticker: 'XIU.TO', weight: 0.5 }] }), /adding up to 100%/);
  await assert.rejects(createAgentClient(settings, transport)({ ...questionArgs, persona: 'custom', holdings: [{ ticker: 'NVDA', weight: 1 }] }), /supported tickers/);
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


test('a custom portfolio is sent with its holdings; samples never send holdings', async () => {
  const bodies = [];
  const transport = async (url, options) => {
    if (options.method === 'POST') { bodies.push(JSON.parse(options.body)); return reply({ jobId, sessionId: 'session-1' }); }
    return reply({ jobId, status: 'DONE', answer: 'ok' });
  };
  const holdings = [{ ticker: 'XIU.TO', weight: 0.6 }, { ticker: 'ENB.TO', weight: 0.4 }];
  await createAgentClient(settings, transport, async () => {})({ ...questionArgs, persona: 'custom', holdings });
  await createAgentClient(settings, transport, async () => {})({ ...questionArgs, holdings });
  assert.deepEqual(bodies[0], { ...questionArgs, persona: 'custom', holdings });
  assert.equal(bodies[1].persona, 'robert');
  assert.equal('holdings' in bodies[1], false);
});

test('the API contract answer object (docs/api_contract.md) is accepted; strings still work', async () => {
  const { normalizeAnswer } = await import('./agent-api.js');
  assert.deepEqual(normalizeAnswer('plain'), { text: 'plain', verdict: null, headline: null, refusal: false, caveat: null });
  const a = normalizeAnswer({ verdict: 'minor', headline: 'H', text: '**MINOR.** body', refusal: false, caveat: '2021–2026' });
  assert.equal(a.verdict, 'MINOR');
  assert.equal(a.text, '**MINOR.** body');
  assert.equal(normalizeAnswer({ verdict: 'BUY NOW', text: 'x' }).verdict, null, 'unknown verdicts are dropped');
  assert.equal(normalizeAnswer({ text: 'NEUTRAL — Gold went up in about half the weeks.' }).verdict, 'NEUTRAL', 'read from the opening line');
  assert.equal(normalizeAnswer({ text: 'NOT LINKED — no link.' }).verdict, 'NOT LINKED');
  assert.equal(normalizeAnswer({ text: 'HELLO — not a verdict' }).verdict, null);
  assert.equal(normalizeAnswer({ text: '', refusal: true }).refusal, true);
  for (const bad of [null, '', '  ', {}, { text: '' }, [], 5]) assert.equal(normalizeAnswer(bad), null);
  const queue = [{ jobId, sessionId: 'session-1' }, { jobId, status: 'RUNNING', stage: 'agent_started', stages: [{ stage: 'queued', t: 'x' }] },
    { job_id: jobId, jobId, status: 'DONE', stage: 'done', answer: { verdict: null, headline: 'H', text: 'Live answer', refusal: false, caveat: 'c' },
      trace: [{ step: 1, tool: 'get_portfolio_exposure', tag: 'measured', ms: 10 }], citations: [{ n: 1, excerpt: 'e', url: 'https://x.test' }], data: {}, toolCalls: [] }];
  const seen = [];
  const r = await createAgentClient(settings, async () => reply(queue.shift()), async () => {})({ ...questionArgs, onProgress: p => seen.push(p.stage ?? p.status) });
  assert.equal(r.answer, 'Live answer');
  assert.equal(r.answerMeta.caveat, 'c');
  assert.equal(r.trace.length, 1);
  assert.ok(seen.includes('agent_started'), 'stages reach the progress panel while polling');
});
