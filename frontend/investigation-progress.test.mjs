import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createAgentClient } from './agent-api.js';
import { JOB_STAGES, createProgress, progressModel, renderProgressPanel, renderInvestigationSteps,
  normalizeStages, normalizeTrace, mountProgress, duration, pipelineModel, renderPipeline, factsFromResult, factText, lookedFor } from './investigation-progress.js';

const jobId = '12345678-1234-1234-1234-123456789abc';
const settings = { submitUrl: 'https://api.example.test/submit', statusUrl: 'https://api.example.test/status/{id}', timeoutMs: 100, jobTimeoutMs: 300, pollIntervalMs: 1 };
const questionArgs = { question: 'Investigate XIU.TO', persona: 'robert', level: 'beginner' };
const reply = data => ({ ok: true, json: async () => data });
const clock = (start = 1000) => { let t = start; const now = () => t; now.add = ms => { t += ms; }; return now; };
const stepLabels = html => [...html.matchAll(/class="ip-label">([^<]*)</g)].map(m => m[1]);
const stepStates = html => [...html.matchAll(/class="ip-step" data-state="(\w+)"/g)].map(m => m[1]);

test('each API status maps to its own label and only reported statuses become steps', () => {
  const now = clock(), p = createProgress(now);
  assert.equal(progressModel(p.record, now()).steps.length, 0, 'nothing is shown before the browser sends');
  assert.equal(progressModel(p.record, now()).title, JOB_STAGES.SUBMITTING);

  p.update({ status: 'SUBMITTING' });
  let html = renderProgressPanel(progressModel(p.record, now()));
  assert.deepEqual(stepLabels(html), ['Sending your question']);
  assert.deepEqual(stepStates(html), ['active']);

  now.add(400); p.update({ status: 'PENDING', jobId, sessionId: 's' });
  now.add(2000); assert.equal(p.update({ status: 'PENDING', jobId }), false, 'repeated polls change nothing');
  now.add(1000); p.update({ status: 'RUNNING', jobId });
  html = renderProgressPanel(progressModel(p.record, now()));
  assert.deepEqual(stepLabels(html), ['Sending your question', 'Queued for investigation', 'Analyzing your portfolio']);
  assert.deepEqual(stepStates(html), ['done', 'done', 'active']);
  assert.match(html, /data-state="running"/);
  assert.match(html, />0\.4 s</);
  assert.match(html, />3\.0 s</, 'queued for 3 s as seen by the browser');
  assert.doesNotMatch(html, /Preparing your results/, 'no backend state reports this stage yet');
  assert.doesNotMatch(html, /\d+\s*%|aria-valuenow/, 'no fabricated percentage');
  assert.match(html, /role="progressbar" aria-label="Investigation in progress, no completion estimate available"/);

  now.add(5000); p.update({ status: 'DONE', jobId });
  p.finish('done');
  const model = progressModel(p.record);
  assert.equal(model.title, 'Investigation complete');
  assert.equal(model.state, 'done');
  assert.deepEqual(model.steps.map(s => s.state), ['done', 'done', 'done', 'done']);
  assert.equal(model.steps[2].ms, 5000);
  assert.equal(model.elapsedMs, 8400);
  assert.doesNotMatch(renderProgressPanel(model), /role="progressbar"/);
});

test('a job the backend skips straight to DONE never shows a RUNNING step', () => {
  const p = createProgress(clock());
  for (const status of ['SUBMITTING', 'PENDING', 'DONE']) p.update({ status, jobId });
  p.finish('done');
  assert.deepEqual(progressModel(p.record).steps.map(s => s.key), ['SUBMITTING', 'PENDING', 'DONE']);
});

test('FAILED is shown as failed; a network error marks the step where it stopped', () => {
  const a = createProgress(clock());
  for (const status of ['SUBMITTING', 'PENDING', 'RUNNING', 'FAILED']) a.update({ status, jobId });
  a.finish('failed');
  let m = progressModel(a.record);
  assert.equal(m.title, 'Investigation failed');
  assert.deepEqual(m.steps.map(s => s.state), ['done', 'done', 'done', 'failed']);

  const b = createProgress(clock());
  b.update({ status: 'SUBMITTING' });
  b.finish('failed');
  m = progressModel(b.record);
  assert.deepEqual(m.steps.map(s => [s.key, s.state]), [['SUBMITTING', 'failed']]);
  assert.equal(b.update({ status: 'RUNNING' }), false, 'a finished record ignores late polls');
});

test('missing or malformed progress metadata is handled without inventing anything', () => {
  for (const record of [undefined, null, {}, { observed: 'x' }, { observed: [{ status: 'THINKING', at: 1 }, null] }]) {
    const m = progressModel(record);
    assert.deepEqual(m.steps, []);
    assert.doesNotThrow(() => renderProgressPanel(m));
  }
  assert.equal(renderInvestigationSteps({}), '', 'no metadata, no empty section');
  assert.equal(renderInvestigationSteps({ record: null, result: { toolCalls: [] } }), '');
  const p = createProgress(clock());
  p.update({ status: 'BOGUS', jobId: 'not-a-uuid', stage: '', stages: 'nope' });
  assert.deepEqual(p.record.observed, []);
  assert.equal(p.record.jobId, null);
  assert.equal(p.record.stages, null);
});

test('old jobs with only toolCalls: steps and figures are rebuilt from the tool outputs', () => {
  const html = renderInvestigationSteps({ result: { durationMs: 18200, citations: [{}, {}], toolCalls: [
    { name: 'get_asset_sensitivity', input: { ticker: 'ENB.TO' }, output: JSON.stringify({ ticker: 'ENB.TO', sensitivity: { beta_simple: 0.092 } }) },
    { name: 'run_scenario', input: { persona: 'robert', oil_shock_pct: '-30' }, output: JSON.stringify({ persona: 'robert', oil_shock_pct: -30, scenario: [{ impact_pct: 1.07 }], holding_impacts: [] }) },
    { name: 'search_evidence', input: { query: 'diesel costs' }, output: JSON.stringify([{ ticker: 'CNQ.TO', section: 'MD&A' }]) },
    { name: 'get_portfolio_exposure', input: { persona: 'robert' }, output: '{"persona": "robert", "holdings": [...[truncated]' },
    { name: 'get_validation', input: { ticker: 'BTC' }, output: '{"error": "unknown ticker", "allowed": []}' },
  ] } });
  assert.match(html, /How RIPPLE reasoned/);
  assert.match(html, /5 steps · 3 measured · 1 source · 18 s/);
  assert.match(html, /<em>ENB\.TO beta \+0\.092<\/em>/);
  assert.match(html, /<em>Robert’s portfolio \+1\.07% at Brent -30%<\/em>/);
  assert.match(html, /<em>CNQ\.TO · MD&amp;A<\/em>/);
  assert.match(html, /Looked for<\/span>Robert’s sample portfolio · Brent -30%/);
  assert.match(html, /Looked for<\/span>“diesel costs”/);
  assert.match(html, /data-kind="source">source/);
  assert.match(html, /ip-tag bad">error/);
  const steps = html.split('class="ip-s"').slice(1);
  assert.doesNotMatch(steps[3], /<em>/, 'a truncated output gives no figures rather than guessed ones');
  assert.doesNotMatch(html, /<h4>Pipeline/, 'no record, no pipeline');
  assert.match(html, /private reasoning is not shown/);
});

test('figures come from tool results only, mirroring agent.claims_from_result', () => {
  assert.deepEqual(factsFromResult('get_portfolio_exposure', { persona: 'custom' }, { persona: 'custom', portfolio_beta: { beta: 0.104 }, holdings: [{ ticker: 'XOM', beta: 0.357 }] }),
    [{ persona: 'custom', beta: 0.104 }, { ticker: 'XOM', beta: 0.357 }]);
  assert.deepEqual(factsFromResult('compare_alternative', {}, { holding: 'TLT', alternative: 'ZST.TO', comparison: { beta_holding: -0.09, beta_alternative: 0.01 } }),
    [{ ticker: 'TLT', beta: -0.09 }, { ticker: 'ZST.TO', beta: 0.01 }]);
  assert.deepEqual(factsFromResult('explain_channel', { ticker: 'TLT' }, { confidence: { label: 'green' } }), [{ ticker: 'TLT', label: 'green' }]);
  assert.deepEqual(factsFromResult('get_asset_sensitivity', {}, { error: 'x' }), []);
  assert.deepEqual(factsFromResult('get_asset_sensitivity', {}, 'not json'), []);
  assert.equal(factText({ persona: 'custom', beta: 0.104 }), 'Your portfolio beta +0.104');
  assert.equal(lookedFor('compare_alternative', { persona: 'robert', holding: 'TLT', alternative: 'ZST.TO' }), 'Robert’s sample portfolio · swap TLT for ZST.TO');
});

test('pipeline: live nodes follow the job statuses; inner AWS stages wait for the recorded trace', () => {
  const now = clock(), p = createProgress(now);
  p.update({ status: 'SUBMITTING' });
  let pm = pipelineModel(p.record, now());
  assert.deepEqual(pm.nodes.map(n => n.state), ['active', 'waiting', 'waiting', 'waiting', 'waiting', 'waiting', 'waiting']);
  now.add(300); p.update({ status: 'PENDING', jobId });
  now.add(2000); p.update({ status: 'RUNNING', jobId });
  now.add(500);
  pm = pipelineModel(p.record, now());
  assert.deepEqual(pm.nodes.map(n => n.state), ['done', 'done', 'active', 'waiting', 'waiting', 'waiting', 'waiting']);
  assert.equal(pm.nodes[1].ms, 2000);
  assert.equal(pm.activeKey, 'agent');
  const live = renderPipeline(pm, { live: true });
  assert.match(live, /Queued<\/span><span class="ip-nsvc">SQS/);
  assert.match(live, /AgentCore/);
  assert.match(live, /data-live-step/);
  assert.match(live, /Athena<\/span><span class="ip-nsvc">Measured data<\/span><span class="sr-only">: not reported yet/);

  // Old backend: DONE without stages -> inner nodes unknown, never ticked.
  const old = createProgress(clock());
  ['SUBMITTING', 'PENDING', 'RUNNING', 'DONE'].forEach(st => old.update({ status: st, jobId }));
  old.finish('done');
  assert.deepEqual(pipelineModel(old.record).nodes.map(n => n.state), ['done', 'done', 'done', 'unknown', 'unknown', 'unknown', 'done']);

  // Live contract (docs/api_contract.md), exactly as the deployed API returned it on 15 Nov 2026.
  now.add(4000);
  const contract = { status: 'DONE', jobId, stage: 'done', stages: [
    { stage: 'queued', t: '2026-11-15T23:39:02Z' }, { stage: 'agent_started', t: '2026-11-15T23:39:04Z' },
    { stage: 'tool:get_portfolio_exposure', t: '2026-11-15T23:39:21Z' }, { stage: 'tool:run_scenario', t: '2026-11-15T23:39:21Z' },
    { stage: 'guardrail', t: '2026-11-15T23:39:21Z' }, { stage: 'done', t: '2026-11-15T23:39:21Z' }],
    answer: { headline: 'Small effect', refusal: false, text: '**MINOR.** Small effect.', caveat: '2021–2026' },
    trace: [{ step: 1, tool: 'get_portfolio_exposure', input_summary: 'persona=robert', output_summary: 'ok', tag: 'measured', ms: 2235 },
      { step: 2, tool: 'run_scenario', input_summary: 'persona=robert, oil_shock_pct=30', output_summary: 'oil 30%: -0.78% (95% -1.34 to -0.22)', tag: 'simulated', ms: 1784 }],
    toolCalls: [{ name: 'get_portfolio_exposure', input: { persona: 'robert' }, output: JSON.stringify({ persona: 'robert', portfolio_beta: { beta: -0.03 }, holdings: [] }) },
      { name: 'run_scenario', input: { persona: 'robert', oil_shock_pct: '30' }, output: '{"persona": "robert", ...[truncated]' }] };
  p.finish('done', contract);
  pm = pipelineModel(p.record);
  assert.deepEqual(pm.nodes.map(n => n.state), ['done', 'done', 'done', 'done', 'skipped', 'done', 'done']);
  assert.equal(pm.nodes[1].ms, 2000, 'queued 23:39:02 -> agent_started 23:39:04');
  assert.equal(pm.nodes[2].ms, 17000);
  assert.equal(pm.nodes[3].ms, 2235 + 1784, 'Athena time from the trace');
  assert.match(pm.nodes[3].summary, /2 measured lookups/);
  const steps = renderInvestigationSteps({ record: p.record, result: contract });
  assert.match(steps, /<h4>Pipeline/);
  assert.doesNotMatch(steps, /does not report the Athena/);
  assert.match(steps, /<em>Robert’s portfolio beta -0\.030<\/em>/, '"ok" summary: figures rebuilt from the matching tool call');
  assert.match(steps, /<em>oil 30%: -0\.78% \(95% -1\.34 to -0\.22\)<\/em>/, 'a real summary is shown as written');
  assert.match(steps, /data-kind="simulated">simulated/);
  assert.match(steps, /Looked for<\/span>Robert’s sample portfolio · Brent \+30%/);
  assert.match(steps, />2\.2 s</);

  // While the agent runs, the live API already reports queued and agent_started.
  const r2 = createProgress(clock());
  r2.update({ status: 'SUBMITTING' });
  r2.update({ status: 'RUNNING', jobId, stages: contract.stages.slice(0, 2) });
  assert.deepEqual(pipelineModel(r2.record).nodes.map(n => n.state), ['done', 'done', 'active', 'waiting', 'waiting', 'waiting', 'waiting']);
  const r3 = createProgress(clock());
  r3.update({ status: 'FAILED', jobId, stages: [...contract.stages.slice(0, 2), { stage: 'failed', t: '2026-11-15T23:39:30Z' }] });
  assert.equal(pipelineModel(r3.record).nodes[2].state, 'failed');

  // Failure while queued marks that node.
  const f = createProgress(clock());
  ['SUBMITTING', 'PENDING'].forEach(st => f.update({ status: st, jobId }));
  f.finish('stopped');
  assert.equal(pipelineModel(f.record).nodes[1].state, 'stopped');
});

test('untrusted strings from the backend are escaped everywhere', () => {
  const evil = '<img src=x onerror=alert(1)>"\'&';
  const p = createProgress(clock());
  p.update({ status: 'RUNNING', jobId, stage: evil, stages: [{ stage: evil, label: evil, summary: evil, status: evil }] });
  const panel = renderProgressPanel(progressModel(p.record));
  const steps = renderInvestigationSteps({ record: p.finish('done'), result: {
    trace: [{ tool: evil, summary: evil, input: { q: evil }, output: evil }], citations: [] } });
  const legacy = renderInvestigationSteps({ result: { toolCalls: [{ name: evil, input: evil, output: { evil } }] } });
  for (const html of [panel, steps, legacy]) {
    assert.doesNotMatch(html, /<img|onerror=alert\(1\)>|="[^"]*"'&/);
    assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
  }
});

test('the live panel announces each new stage once and stops its timer', () => {
  const now = clock(), timers = [];
  const make = () => {
    const el = { innerHTML: '', textContent: '', querySelector: () => null };
    return el;
  };
  const live = make(), panel = make();
  let renders = 0;
  Object.defineProperty(panel, 'innerHTML', { get: () => '', set: () => { renders++; } });
  const host = { innerHTML: '', querySelector: sel => (sel === '[data-ip-live]' ? live : panel) };
  const handle = mountProgress(host, { now, setTimer: fn => { timers.push({ fn, on: true }); return timers.length - 1; }, clearTimer: id => { timers[id].on = false; } });
  assert.match(host.innerHTML, /role="status" aria-live="polite"/);
  assert.match(host.innerHTML, /aria-live="off"/, 'the panel itself is not re-announced');
  handle.update({ status: 'SUBMITTING' });
  const afterSubmit = renders;
  handle.update({ status: 'SUBMITTING' });
  assert.equal(renders, afterSubmit, 'no re-render when nothing changed');
  handle.update({ status: 'PENDING', jobId });
  assert.equal(live.textContent, 'Queued for investigation');
  timers[0].fn();
  handle.finish('stopped');
  assert.equal(live.textContent, 'Stopped waiting');
  assert.equal(timers[0].on, false);
});

test('cancelling and timing out the real client leave an honest record', async () => {
  // Cancel while the job is queued.
  const controller = new AbortController();
  const p = createProgress(clock());
  const queue = [{ jobId, sessionId: 'session-1' }, { jobId, status: 'PENDING' }];
  const ask = createAgentClient(settings, async () => reply(queue.shift() ?? { jobId, status: 'PENDING' }), async () => { controller.abort(); throw controller.signal.reason; });
  await assert.rejects(ask({ ...questionArgs, signal: controller.signal, onProgress: x => p.update(x) }));
  p.finish('stopped');
  let m = progressModel(p.record);
  assert.equal(m.title, 'Stopped waiting');
  assert.deepEqual(m.steps.map(s => [s.key, s.state]), [['SUBMITTING', 'done'], ['PENDING', 'stopped']]);

  // Job never finishes within jobTimeoutMs.
  const t = createProgress();
  const slow = createAgentClient({ ...settings, jobTimeoutMs: 30, pollIntervalMs: 5 },
    async (url, o) => reply(o.method === 'POST' ? { jobId, sessionId: 's' } : { jobId, status: 'RUNNING' }));
  const error = await slow({ ...questionArgs, onProgress: x => t.update(x) }).catch(e => e);
  assert.equal(error.name, 'TimeoutError');
  t.finish('timeout');
  m = progressModel(t.record);
  assert.equal(m.title, 'Stopped: waiting timed out');
  assert.equal(m.steps.at(-1).key, 'RUNNING');
  assert.equal(m.steps.at(-1).state, 'stopped');
});

test('durations read naturally and reduced motion is honoured in the stylesheet', async () => {
  assert.deepEqual([duration(400), duration(1500), duration(59_400), duration(65_000), duration(null), duration(-1)],
    ['0.4 s', '1.5 s', '59 s', '1 min 05 s', '', '']);
  const css = await readFile(new URL('./investigation-progress.css', import.meta.url), 'utf8');
  const reduced = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'));
  assert.ok(reduced.length > 40);
  for (const sel of ['.ip-spin', '.ip-track span', '.ip-mark::before']) assert.ok(reduced.includes(sel), sel);
  assert.match(reduced, /animation: none !important/);
  for (const page of ['index.html']) {
    assert.match(await readFile(new URL(`./${page}`, import.meta.url), 'utf8'), /investigation-progress\.css/, page);
  }
});

test('figures for the contract tools (get_portfolio_facts, test_shield, rates scenarios)', () => {
  const facts = factsFromResult('get_portfolio_facts', { persona: 'robert' }, { persona: 'robert',
    protection: { stock_side: 'XIU.TO', n_worst_weeks: 27, avg_bond_return_pct: -0.17 }, risk_share: { rates: 0.31, stocks: 0.42, oil: 0.02 }, facts: { max_drawdown_pct: -18.4 } });
  assert.deepEqual(facts.map(f => factText(f)), ['Bonds -0.17% on average in the 27 worst XIU.TO weeks', 'Risk share (R²): rates 0.31, stocks 0.42, oil 0.02', 'Max drawdown -18.40%']);
  assert.equal(factText(factsFromResult('test_shield', {}, { ticker: 'GLD', worst_weeks: { label: 'WORKING', avg_pct_worst: 0.4, weeks: 27, weeks_up: 17 } })[0]),
    'GLD (WORKING): +0.40% on average in 27 worst weeks, up in 17');
  assert.equal(factText(factsFromResult('run_scenario', {}, { shock_type: 'rates', rates_shock_bp: 100, total: { impact_pct: -4.1, per_100k: -4100 } })[0]),
    'Rates +100 bp: portfolio -4.10% (-4,100 per $100k)');
  assert.equal(lookedFor('run_scenario', 'persona=robert, shock_type=rates, rates_shock_bp=100'), 'Robert’s sample portfolio · rates +100 bp');
});
