// Investigation progress: a live panel while a backend job runs, then a compact "View investigation steps"
// record under the answer. It only shows what the backend actually reported:
//   * today: the job statuses SUBMITTING (set by this browser when it sends), PENDING, RUNNING, DONE, FAILED,
//     plus toolCalls [{ name, input, output }] and durationMs on the finished job;
//   * later (proposed contract, not deployed): `stage`, `stages[]` and `trace[]`. They are read only when
//     present and well-formed; nothing is inferred from their absence.
// There is no percentage: the API reports no progress fraction, so the track is indeterminate.
// Times between statuses are measured in this browser (polling every ~1.2 s) and labelled as such.
import { escapeHTML as esc, finite, number } from './formatters.js';

export const JOB_STAGES = Object.freeze({
  SUBMITTING: 'Sending your question',
  PENDING: 'Queued for investigation',
  RUNNING: 'Analyzing your portfolio',
  DONE: 'Investigation complete',
  FAILED: 'Investigation failed',
});
// Labels for stage names the upcoming contract may report. Used only if the backend sends that stage.
const NAMED_STAGES = { preparing: 'Preparing your results', preparing_results: 'Preparing your results',
  analyzing: 'Analyzing your portfolio', gathering_evidence: 'Gathering evidence', evidence: 'Gathering evidence',
  queued: 'Queued for investigation', submitted: 'Sending your question', complete: 'Investigation complete', done: 'Investigation complete' };
const OUTCOME_TITLES = { done: 'Investigation complete', failed: 'Investigation failed', stopped: 'Stopped waiting', timeout: 'Stopped: waiting timed out' };
const STEP_STATES = { pending: 'pending', queued: 'pending', running: 'active', active: 'active', in_progress: 'active', started: 'active',
  done: 'done', complete: 'done', completed: 'done', succeeded: 'done', success: 'done', ok: 'done',
  failed: 'failed', error: 'failed', skipped: 'skipped', stopped: 'stopped' };
const MAX_STAGES = 20, MAX_TRACE = 40, MAX_TEXT = 300;

const text = (v, max = MAX_TEXT) => (typeof v === 'string' && v.trim() ? v.trim().slice(0, max) : null);
const ms = v => (finite(v) && v >= 0 && v < 864e5 ? v : null);
const plain = v => v && typeof v === 'object' && !Array.isArray(v);
const humanize = key => key.replace(/[_-]+/g, ' ').toLowerCase().replace(/^\w/, c => c.toUpperCase());
export function stageLabel(key) {
  if (Object.hasOwn(JOB_STAGES, key)) return JOB_STAGES[key];
  const k = String(key).trim().toLowerCase().replace(/[\s-]+/g, '_');
  return NAMED_STAGES[k] ?? humanize(String(key).trim().slice(0, 80));
}

/** Future `stages[]`: keep only well-formed recorded events. Returns null when nothing usable was sent. */
export function normalizeStages(raw) {
  if (!Array.isArray(raw)) return null;
  const out = raw.filter(plain).slice(0, MAX_STAGES).map(s => {
    const key = text(s.stage ?? s.name ?? s.id ?? s.key, 80);
    if (!key) return null;
    const status = String(s.status ?? s.state ?? '').toLowerCase();
    const at = typeof s.t === 'string' ? Date.parse(s.t) : finite(s.at) ? s.at : NaN;
    return { key, label: text(s.label ?? s.title, 120) ?? stageLabel(key), state: STEP_STATES[status] ?? 'done',
      ms: ms(s.duration_ms ?? s.durationMs ?? s.ms), summary: text(s.summary ?? s.detail), source: 'backend', ...(Number.isFinite(at) ? { at } : {}) };
  }).filter(Boolean);
  return out.length ? out : null;
}

const SOURCE_TOOLS = ['search_evidence'];
const num = v => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const word = v => (typeof v === 'string' && v ? v.slice(0, 80) : null);

/**
 * Figures from one tool result, mirroring agent.claims_from_result (agent/agent.py). Used for jobs that only
 * stored toolCalls; outputs cut short by the backend ("...[truncated]") are not parsed, so give no figures.
 */
export function factsFromResult(name, input, output) {
  let r = output;
  if (typeof r === 'string') { try { r = JSON.parse(r); } catch { return []; } }
  if (SOURCE_TOOLS.includes(name)) return (Array.isArray(r) ? r : []).filter(x => plain(x) && !x.error).map(x => ({ ticker: word(x.ticker), section: word(x.section) }));
  if (!plain(r) || r.error) return [];
  const p = plain(input) ? input : {};
  const ticker = word(r.ticker) ?? word(p.ticker), persona = word(r.persona) ?? word(p.persona);
  const out = [], rows = k => (Array.isArray(r[k]) ? r[k].filter(plain) : []), box = k => (plain(r[k]) ? r[k] : {});
  const add = (key, subject, fields) => {
    const f = Object.fromEntries(Object.entries(fields).filter(([, v]) => v !== null && v !== undefined));
    if (subject && Object.keys(f).length) out.push({ [key]: subject, ...f });
  };
  if (name === 'get_portfolio_exposure') {
    add('persona', persona, { beta: num(box('portfolio_beta').beta) });
    rows('holdings').forEach(h => add('ticker', word(h.ticker), { beta: num(h.beta) }));
  } else if (name === 'get_asset_sensitivity') add('ticker', ticker, { beta: num(box('sensitivity').beta_simple) });
  else if (name === 'explain_channel') add('ticker', ticker, { label: word(box('confidence').label) });
  else if (name === 'get_validation') add('ticker', ticker, { label: word(box('validation').label) });
  else if (name === 'run_scenario') {
    const shock = num(r.oil_shock_pct);
    rows('scenario').forEach(x => add('persona', persona, { impact_pct: num(x.impact_pct), shock_pct: shock }));
    rows('holding_impacts').forEach(x => add('ticker', word(x.ticker), { impact_pct: num(x.impact_pct), shock_pct: shock }));
  } else if (name === 'compare_alternative') {
    add('ticker', word(r.holding), { beta: num(box('comparison').beta_holding) });
    add('ticker', word(r.alternative), { beta: num(box('comparison').beta_alternative) });
  }
  // Tools added in docs/api_contract.md; wording mirrors agent._summarize_output.
  const pct = v => (num(v) === null ? null : `${number(v, 2, true)}%`);
  if (name === 'get_portfolio_facts') {
    const prot = box('protection'), risk = box('risk_share'), facts = box('facts');
    if (pct(prot.avg_bond_return_pct)) out.push({ text: `Bonds ${pct(prot.avg_bond_return_pct)} on average in the ${prot.n_worst_weeks ?? ''} worst ${word(prot.stock_side) ?? 'stock'} weeks`.replace(/\s+/g, ' ') });
    const shares = ['rates', 'stocks', 'oil'].filter(k => num(risk[k]) !== null).map(k => `${k} ${number(risk[k], 2)}`);
    if (shares.length) out.push({ text: `Risk share (R²): ${shares.join(', ')}` });
    if (pct(facts.max_drawdown_pct)) out.push({ text: `Max drawdown ${pct(facts.max_drawdown_pct)}` });
  } else if (name === 'test_shield') {
    const w = box('worst_weeks');
    out.push({ text: num(w.avg_pct_worst) !== null
      ? `${word(r.ticker) ?? 'Shield'}${w.label ? ` (${w.label})` : ''}: ${pct(w.avg_pct_worst)} on average in ${w.weeks ?? '?'} worst weeks, up in ${w.weeks_up ?? '?'}`
      : `${word(r.ticker) ?? 'Shield'}: no result for this portfolio` });
  } else if (name === 'run_scenario' && r.shock_type === 'rates') {
    const total = box('total');
    if (pct(total.impact_pct)) out.push({ text: `Rates ${number(Number(r.rates_shock_bp), 0, true)} bp: portfolio ${pct(total.impact_pct)}${num(total.per_100k) !== null ? ` (${number(total.per_100k, 0, true)} per $100k)` : ''}` });
  }
  return out.slice(0, 12);
}

/** Agent steps: `trace[]` when the backend recorded it, otherwise rebuilt from `toolCalls[]`. Nothing is invented. */
const TAGS = ['measured', 'source', 'documented', 'simulated'];
export function normalizeTrace(result = {}) {
  const fromTrace = Array.isArray(result.trace) && result.trace.some(plain);
  const rows = (fromTrace ? result.trace : Array.isArray(result.toolCalls) ? result.toolCalls : []).filter(plain).slice(0, MAX_TRACE);
  const calls = Array.isArray(result.toolCalls) ? result.toolCalls.filter(plain) : [];
  const used = new Set();
  return rows.map(r => {
    const name = text(r.tool ?? r.name, 120) ?? 'Unnamed tool';
    // The matching stored tool call (same tool, in order) supplies raw input/output and, if needed, figures.
    const callIndex = fromTrace ? calls.findIndex((c, i) => !used.has(i) && c.name === name) : -1;
    if (callIndex >= 0) used.add(callIndex);
    const call = fromTrace ? calls[callIndex] : r;
    const kindRaw = String(r.tag ?? r.kind ?? r.type ?? '').toLowerCase();
    const kind = TAGS.includes(kindRaw) ? kindRaw : ['evidence', 'retrieval', 'citation'].includes(kindRaw) ? 'source'
      : SOURCE_TOOLS.includes(name) ? 'source' : 'measured';
    const outSummary = text(r.output_summary ?? r.summary);
    let failed = ['failed', 'error'].includes(String(r.status ?? '').toLowerCase()) || /^error\b/i.test(outSummary ?? '');
    if (call && typeof call.output === 'string' && /^\s*\{\s*"error"/.test(call.output)) failed = true;
    const summary = outSummary && !/^ok$/i.test(outSummary) && !failed ? outSummary : null;
    let facts = [];
    if (!failed) facts = fromTrace && Array.isArray(r.facts) ? r.facts.filter(plain).slice(0, 12) : call ? factsFromResult(name, call.input, call.output) : [];
    return {
      name, kind, facts, failed, summary,
      ms: ms(r.duration_ms ?? r.durationMs ?? r.ms),
      evidence: kind === 'source' || kind === 'documented',
      input: call?.input ?? (typeof r.input_summary === 'string' ? r.input_summary : r.input), output: call?.output ?? r.output,
      inputSummary: typeof r.input_summary === 'string' ? r.input_summary : null,
    };
  });
}

// ---------- the record ----------
// A plain JSON object so it can be saved with the chat message and re-rendered after a reload.
export function createProgress(now = Date.now) {
  const record = { v: 1, startedAt: now(), endedAt: null, outcome: null, jobId: null, observed: [], stage: null, stages: null, error: null };
  return {
    record,
    /** Feed every onProgress payload. Returns true when what the panel shows has changed. */
    update(p = {}) {
      if (record.outcome) return false;
      let changed = false;
      if (Object.hasOwn(JOB_STAGES, p.status) && record.observed.at(-1)?.status !== p.status) {
        record.observed.push({ status: p.status, at: now() });
        changed = true;
      }
      if (typeof p.jobId === 'string' && /^[0-9a-f-]{36}$/i.test(p.jobId) && record.jobId !== p.jobId) { record.jobId = p.jobId; changed = true; }
      const stage = text(p.stage, 80);
      if (stage && stage !== record.stage) { record.stage = stage; changed = true; }
      const stages = normalizeStages(p.stages);
      if (stages && JSON.stringify(stages) !== JSON.stringify(record.stages)) { record.stages = stages; changed = true; }
      if (Array.isArray(p.trace) && p.trace.length) {
        record.toolMs = p.trace.filter(plain).slice(0, MAX_TRACE).map(t => ({ tool: text(t.tool ?? t.name, 120), ms: ms(t.ms ?? t.duration_ms) }));
      }
      if (plain(p.answer) && p.answer.refusal === true) record.refusal = true;
      return changed;
    },
    /** outcome: 'done' | 'failed' | 'stopped' | 'timeout' */
    finish(outcome, result) {
      if (record.outcome) return record;
      if (result) this.update(result);
      record.outcome = OUTCOME_TITLES[outcome] ? outcome : 'failed';
      record.endedAt = now();
      return record;
    },
  };
}

/** Turn a record into what is displayed. `at` is the current time for the live elapsed counter. */
export function progressModel(record, at = Date.now()) {
  const r = plain(record) ? record : {};
  const observed = (Array.isArray(r.observed) ? r.observed : []).filter(o => plain(o) && Object.hasOwn(JOB_STAGES, o.status) && finite(o.at));
  const end = finite(r.endedAt) ? r.endedAt : null;
  const outcome = OUTCOME_TITLES[r.outcome] ? r.outcome : null;
  const backend = normalizeStages(r.stages);
  let steps;
  if (backend) {
    steps = backend.map(s => ({ ...s }));
  } else {
    steps = observed.map((o, i) => {
      const next = observed[i + 1]?.at ?? end;
      const last = i === observed.length - 1;
      const state = o.status === 'FAILED' ? 'failed' : o.status === 'DONE' ? 'done' : !last ? 'done' : outcome ? 'done' : 'active';
      return { key: o.status, label: JOB_STAGES[o.status], state, ms: o.status === 'DONE' || o.status === 'FAILED' ? null : next !== null ? next - o.at : null, source: 'observed' };
    });
  }
  // A job that ended without the backend saying DONE or FAILED (network error, stop, timeout): mark where it stood.
  if (outcome && outcome !== 'done') {
    const last = [...steps].reverse().find(s => s.state === 'active' || (s.state === 'done' && !['DONE', 'FAILED'].includes(s.key)));
    if (last && !steps.some(s => s.state === 'failed')) last.state = outcome === 'failed' ? 'failed' : 'stopped';
  }
  const active = steps.find(s => s.state === 'active');
  const title = outcome ? OUTCOME_TITLES[outcome] : active?.label ?? (r.stage ? stageLabel(r.stage) : steps.at(-1)?.label) ?? JOB_STAGES.SUBMITTING;
  const detail = !outcome && !backend && r.stage && stageLabel(r.stage) !== title ? stageLabel(r.stage) : null;
  return { title, detail, state: outcome ?? 'running', steps, source: backend ? 'backend' : 'observed', jobId: text(r.jobId, 40),
    elapsedMs: finite(r.startedAt) ? Math.max(0, (end ?? at) - r.startedAt) : null };
}

// ---------- formatting ----------
export function duration(value) {
  if (!finite(value) || value < 0) return '';
  if (value < 9950) return `${(value / 1000).toFixed(1)} s`;
  const s = Math.round(value / 1000);
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, '0')} s`;
}
const ICONS = {
  done: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 8.5l2.5 2.5L12 5.5"/></svg>',
  failed: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5 5l6 6M11 5l-6 6"/></svg>',
  stopped: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5 8h6"/></svg>',
  skipped: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5 8h6"/></svg>',
  active: '<span class="ip-spin" aria-hidden="true"></span>',
  pending: '<span class="ip-dot" aria-hidden="true"></span>',
};
const STATE_WORDS = { done: 'completed', failed: 'failed', stopped: 'interrupted', skipped: 'skipped', active: 'in progress', pending: 'not started' };

function stepsHTML(steps, { live = false } = {}) {
  return `<ol class="ip-steps">${steps.map((s, i) => `<li class="ip-step" data-state="${s.state}" style="--i:${i}">
      <span class="ip-icon">${ICONS[s.state] ?? ICONS.done}</span>
      <span class="ip-step-text"><span class="ip-label">${esc(s.label)}</span><span class="sr-only">, ${STATE_WORDS[s.state] ?? 'completed'}</span>${s.summary ? `<span class="ip-summary">${esc(s.summary)}</span>` : ''}</span>
      <span class="ip-dur"${live && s.state === 'active' ? ' data-live-step' : ''}>${esc(duration(s.ms))}</span></li>`).join('')}</ol>`;
}

// ---------- AWS pipeline ----------
export const PIPELINE = Object.freeze([
  { key: 'received', label: 'Received', service: 'API Gateway' },
  { key: 'queued', label: 'Queued', service: 'SQS' },
  { key: 'agent', label: 'Agent run', service: 'AgentCore' },
  { key: 'athena', label: 'Athena', service: 'Measured data' },
  { key: 'kb', label: 'Sources', service: 'Knowledge Base' },
  { key: 'guardrail', label: 'Guardrail', service: 'Bedrock' },
  { key: 'done', label: 'Done', service: '' },
]);
const LIVE = { SUBMITTING: 0, PENDING: 1, RUNNING: 2 };      // job status -> pipeline node it puts in progress
const NODE_STATUS = ['SUBMITTING', 'PENDING', 'RUNNING'];     // node -> job status whose time it measures

/**
 * Pipeline nodes from what was reported. Live, only Received / Queued / Agent can be confirmed (job statuses);
 * Athena, Sources and Guardrail stay "waiting" until the finished job's recorded stages say what happened.
 * An older backend that records no stages leaves them "unknown" rather than guessed.
 */
export function pipelineModel(record, at = Date.now()) {
  const r = plain(record) ? record : {};
  const observed = (Array.isArray(r.observed) ? r.observed : []).filter(o => plain(o) && Object.hasOwn(JOB_STAGES, o.status) && finite(o.at));
  const outcome = OUTCOME_TITLES[r.outcome] ? r.outcome : null;
  const end = finite(r.endedAt) ? r.endedAt : null;
  const recorded = new Map((normalizeStages(r.stages) ?? []).filter(st => PIPELINE.some(n => n.key === st.key)).map(st => [st.key, st]));
  const contract = contractNodes(r);
  if (contract) for (const [k, v] of contract) recorded.set(k, v);
  const statuses = observed.map(o => o.status);
  const timeOf = st => observed.find(o => o.status === st)?.at ?? null;
  const done = statuses.includes('DONE'), failedJob = statuses.includes('FAILED');
  const lastLive = Math.max(-1, ...statuses.filter(st => st in LIVE).map(st => LIVE[st]));
  const nodes = PIPELINE.map((n, i) => {
    const rec = recorded.get(n.key);
    if (rec) return { ...n, state: rec.state, ms: rec.ms, summary: rec.summary };
    let state;
    if (n.key === 'done') state = done ? 'done' : 'waiting';
    else if (i <= 2) state = done || i < lastLive ? 'done' : i === lastLive ? (failedJob ? 'failed' : 'active') : 'waiting';
    else state = done ? 'unknown' : 'waiting';
    let t = null;
    if (i <= 2) {
      const from = timeOf(NODE_STATUS[i]);
      const to = observed.find(o => o.at > (from ?? Infinity) && o.status !== NODE_STATUS[i])?.at ?? null;
      t = from !== null && to !== null ? to - from : null;
    }
    return { ...n, state, ms: t, summary: null };
  });
  if (recorded.size && recorded.has('agent') && !recorded.has('done') && done) nodes[6].state = 'done';
  if (outcome && outcome !== 'done') {
    const live = nodes.find(n => n.state === 'active');
    if (live) live.state = outcome === 'failed' ? 'failed' : 'stopped';
  }
  const active = nodes.find(n => n.state === 'active');
  return { nodes, activeKey: active?.key ?? null, activeSince: active ? timeOf(NODE_STATUS[PIPELINE.indexOf(active)]) : null,
    recorded: recorded.size > 0, elapsedMs: finite(r.startedAt) ? Math.max(0, (end ?? at) - r.startedAt) : null };
}

/**
 * docs/api_contract.md stages ({stage, t}: queued, agent_started, tool:<name>, guardrail, done, failed) as pipeline
 * nodes. Tool stages are written when the agent returns, so Athena/Sources durations come from the trace's ms.
 */
function contractNodes(r) {
  const list = normalizeStages(r.stages) ?? [];
  const keys = list.map(s => s.key);
  if (!keys.some(k => ['queued', 'agent_started', 'guardrail', 'failed'].includes(k) || k.startsWith('tool:'))) return null;
  const at = k => list.find(s => s.key === k)?.at ?? null;
  const has = k => keys.includes(k);
  const span = (a, b) => (finite(a) && finite(b) && b >= a ? b - a : null);
  const end = has('done') || has('failed');
  const tools = keys.filter(k => k.startsWith('tool:')).map(k => k.slice(5));
  const sumMs = pick => {
    const rows = (Array.isArray(r.toolMs) ? r.toolMs : []).filter(t => t && pick(t.tool) && finite(t.ms));
    return rows.length ? rows.reduce((t, x) => t + x.ms, 0) : null;
  };
  const isKb = name => SOURCE_TOOLS.includes(name);
  const athena = tools.filter(t => !isKb(t)), kb = tools.filter(isKb);
  const count = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const out = new Map();
  out.set('received', { state: 'done', ms: null, summary: 'API Gateway, cascade-submit' });
  out.set('queued', has('agent_started') || end ? { state: 'done', ms: span(at('queued'), at('agent_started')), summary: 'SQS' } : { state: 'active', ms: null, summary: 'SQS' });
  if (has('agent_started')) {
    out.set('agent', { state: has('failed') ? 'failed' : has('done') ? 'done' : 'active',
      ms: end ? span(at('agent_started'), at('done') ?? at('failed')) : null, summary: 'Bedrock AgentCore' });
  } else if (has('failed')) out.set('agent', { state: 'failed', ms: null, summary: null });
  if (has('done')) {
    out.set('athena', athena.length ? { state: 'done', ms: sumMs(t => !isKb(t)), summary: `${count(athena.length, 'measured lookup', 'measured lookups')} via cascade-tools` }
      : { state: 'skipped', ms: null, summary: 'Not needed for this question' });
    out.set('kb', kb.length ? { state: 'done', ms: sumMs(isKb), summary: count(kb.length, 'search', 'searches') }
      : { state: 'skipped', ms: null, summary: 'Not needed for this question' });
    out.set('guardrail', has('guardrail') ? { state: 'done', ms: null, summary: r.refusal ? 'Intervened: the request was declined' : 'Checked; nothing blocked' }
      : { state: 'unknown', ms: null, summary: null });
    out.set('done', { state: 'done', ms: null, summary: null });
  }
  return out;
}

const NODE_WORDS = { done: 'done', failed: 'failed', stopped: 'interrupted', skipped: 'not needed', active: 'in progress',
  waiting: 'not reported yet', unknown: 'not reported by this backend version', pending: 'not reported yet' };
export function renderPipeline(pm, { live = false } = {}) {
  return `<ol class="ip-pipe" aria-label="AWS pipeline">${pm.nodes.map((n, i) => `<li class="ip-node" data-state="${esc(n.state)}" style="--i:${i}"${n.summary ? ` title="${esc(n.summary)}"` : ''}>
      <span class="ip-ndot" aria-hidden="true">${n.state === 'done' ? ICONS.done : n.state === 'failed' ? ICONS.failed : n.state === 'skipped' || n.state === 'stopped' ? ICONS.stopped : ''}</span>
      <span class="ip-ntext"><span class="ip-nlabel">${esc(n.label)}</span>${n.service ? `<span class="ip-nsvc">${esc(n.service)}</span>` : ''}<span class="sr-only">: ${NODE_WORDS[n.state] ?? n.state}${n.summary ? `. ${esc(n.summary)}` : ''}</span></span>
      <span class="ip-ndur"${live && n.state === 'active' ? ' data-live-step' : ''}>${esc(duration(n.ms))}</span>
    </li>`).join('')}</ol>`;
}

/** Live panel shown while the job runs (and frozen in its final state if the job does not answer). */
export function renderProgressPanel(model, pipeline = null) {
  const running = model.state === 'running';
  return `<div class="ip" data-state="${esc(model.state)}">
    <div class="ip-head">
      <span class="ip-mark" aria-hidden="true"><i></i></span>
      <span class="ip-titles"><span class="ip-title">${esc(model.title)}</span>${model.detail ? `<span class="ip-detail">${esc(model.detail)}</span>` : ''}</span>
      <span class="ip-elapsed" aria-hidden="true" data-elapsed>${esc(duration(model.elapsedMs))}</span>
    </div>
    ${pipeline ? `<div class="ip-pipe-wrap"${running ? ' role="progressbar" aria-label="Investigation in progress, no completion estimate available"' : ''}>${renderPipeline(pipeline, { live: running })}</div>`
      : `<div class="ip-track"${running ? ' role="progressbar" aria-label="Investigation in progress, no completion estimate available"' : ' aria-hidden="true"'}><span></span></div>
    ${model.steps.length ? stepsHTML(model.steps, { live: running }) : ''}`}
  </div>`;
}

// ---------- "How AION reasoned" ----------
const TOOL_NAMES = { get_portfolio_exposure: 'Portfolio exposure', get_portfolio_facts: 'Portfolio facts', test_shield: 'Shield test', get_asset_sensitivity: 'Ticker sensitivity', explain_channel: 'Transmission channel',
  run_scenario: 'Scenario', compare_alternative: 'Alternative', get_validation: 'Validation checks', search_evidence: 'Source search' };
const cap = v => String(v).charAt(0).toUpperCase() + String(v).slice(1);
const subjectOf = f => f.ticker ?? (f.persona === 'custom' ? 'Your portfolio' : f.persona ? `${cap(f.persona)}’s portfolio` : '');
export function factText(f, kind) {
  if (word(f.text)) return f.text;
  if (kind === 'source') return `${f.ticker || 'Macro'}${f.section ? ` · ${f.section}` : ''}`;
  const who = subjectOf(f);
  if (num(f.impact_pct) !== null) return `${who} ${number(f.impact_pct, 2, true)}%${num(f.shock_pct) !== null ? ` at Brent ${number(f.shock_pct, 0, true)}%` : ''}`;
  if (num(f.beta) !== null) return `${who} beta ${number(f.beta, 3, true)}`;
  if (word(f.label)) return `${who} confidence: ${f.label}`;
  if (word(f.verdict)) return `${who}: ${f.verdict}`;
  return who;
}
export function lookedFor(name, input) {
  const p = plain(input) ? input : typeof input === 'string'
    ? Object.fromEntries(input.split(/,\s*(?=[a-z_]+=)/).map(kv => kv.split('=')).filter(x => x.length >= 2).map(([k, ...v]) => [k.trim(), v.join('=').trim()]))
    : {};
  const parts = [];
  if (p.persona) parts.push(String(p.persona).toLowerCase() === 'custom' ? 'your portfolio' : `${cap(p.persona)}’s sample portfolio`);
  if (p.holding && p.alternative) parts.push(`swap ${p.holding} for ${p.alternative}`);
  else if (p.ticker && name !== 'search_evidence') parts.push(String(p.ticker));
  if (p.oil_shock_pct !== undefined && p.oil_shock_pct !== 'None' && p.oil_shock_pct !== null) parts.push(`Brent ${number(Number(p.oil_shock_pct), 0, true)}%`);
  if (p.rates_shock_bp !== undefined && p.rates_shock_bp !== 'None' && p.rates_shock_bp !== null) parts.push(`rates ${number(Number(p.rates_shock_bp), 0, true)} bp`);
  if (p.query) parts.push(`“${String(p.query).slice(0, 120)}”${p.ticker ? ` in ${p.ticker}` : ''}`);
  return parts.join(' · ');
}

const json = v => (typeof v === 'string' ? v : JSON.stringify(v ?? null, null, 2));
/**
 * The collapsible "How AION reasoned" record under an answer: the AWS pipeline it went through and each
 * agent step (tool, what it looked for, the figures it got back, measured or source). Returns '' when there
 * is no execution metadata at all, so old messages and offline answers do not get an empty section.
 */
export function renderInvestigationSteps({ record, result = {} } = {}) {
  const pm = plain(record) ? pipelineModel(record) : null;
  const hasPipe = pm && pm.nodes.some(n => n.state !== 'waiting');
  const trace = normalizeTrace(result);
  const total = ms(result.durationMs);
  if (!hasPipe && !trace.length) return '';
  const measured = trace.filter(t => t.kind === 'measured' && !t.failed).length, sources = trace.filter(t => (t.kind === 'source' || t.kind === 'documented') && !t.failed).length;
  const meta = [trace.length && `${trace.length} step${trace.length > 1 ? 's' : ''}`, measured && `${measured} measured`, sources && `${sources} source${sources > 1 ? 's' : ''}`,
    total !== null && duration(total)].filter(Boolean).join(' · ');
  const jobId = plain(record) ? text(record.jobId, 40) : null;
  return `<details class="ip-record">
    <summary><svg class="ip-chev" viewBox="0 0 16 16" aria-hidden="true"><path d="M6 4l4 4-4 4"/></svg><span>How AION reasoned</span>${meta ? `<span class="ip-meta">${esc(meta)}</span>` : ''}</summary>
    <div class="ip-record-body">
      ${hasPipe ? `<section><h4>Pipeline</h4>${renderPipeline(pm)}
        ${pm.recorded ? '' : '<p class="ip-src">Times between Received, Queued and Agent are as seen by this browser. This backend version does not report the Athena, source and guardrail stages.</p>'}</section>` : ''}
      ${trace.length ? `<section><h4>Agent steps</h4><ol class="ip-steps2">${trace.map((t, i) => {
        const found = t.summary ? t.summary.split(/;\s+/).filter(Boolean) : t.facts.map(f => factText(f, t.kind === 'documented' ? 'source' : t.kind)).filter(Boolean);
        const looked = lookedFor(t.name, t.input);
        return `<li class="ip-s"${t.failed ? ' data-state="failed"' : ''}>
          <span class="ip-snum" aria-hidden="true">${i + 1}</span>
          <div class="ip-sbody">
            <div class="ip-shead"><b>${esc(TOOL_NAMES[t.name] ?? t.name)}</b><code>${esc(t.name)}</code>
              ${t.failed ? '<span class="ip-tag bad">error</span>' : `<span class="ip-tag" data-kind="${t.kind}">${t.kind}</span>`}<span class="ip-dur">${esc(duration(t.ms))}</span></div>
            ${looked ? `<p class="ip-sline"><span>Looked for</span>${esc(looked)}</p>` : ''}
            ${found.length ? `<p class="ip-sline"><span>${t.kind === 'source' ? 'Found' : 'Got'}</span>${found.slice(0, 5).map(x => `<em>${esc(x)}</em>`).join('')}${found.length > 5 ? `<em class="more">+${found.length - 5} more</em>` : ''}</p>`
              : t.failed ? '<p class="ip-sline"><span>Got</span>The tool returned an error.</p>' : ''}
            ${t.input !== undefined || t.output !== undefined ? `<details class="ip-io"><summary>Raw input and output</summary><pre>${esc(json(t.input ?? {}))}</pre><pre>${esc(json(t.output))}</pre></details>` : ''}
          </div></li>`;
      }).join('')}</ol>
      <p class="ip-src"><span class="ip-tag" data-kind="measured">measured</span> computed from the weekly data in Athena. <span class="ip-tag" data-kind="source">source</span> passages from documents.${trace.some(t => t.kind === 'simulated') ? ' <span class="ip-tag" data-kind="simulated">simulated</span> a scenario applied to historical sensitivities.' : ''}</p></section>` : ''}
      <p class="ip-foot">${[jobId && `Job ${esc(jobId)}`, total !== null && `Backend run time ${esc(duration(total))}`].filter(Boolean).join(' · ')}</p>
      <p class="ip-src">Figures are taken from the tool results, not from the model’s prose. The model’s private reasoning is not shown.</p>
    </div>
  </details>`;
}

/**
 * Mount a live panel in `host`. Re-renders only when the reported state changes; the elapsed counter
 * ticks separately (hidden from screen readers), and a polite live region announces each new stage once.
 */
export function mountProgress(host, { now = Date.now, setTimer = setInterval, clearTimer = clearInterval } = {}) {
  const progress = createProgress(now);
  host.innerHTML = '<p class="sr-only" role="status" aria-live="polite" data-ip-live></p><div aria-live="off" data-ip-panel></div>';
  const live = host.querySelector('[data-ip-live]'), panel = host.querySelector('[data-ip-panel]');
  let announced = '';
  const draw = () => {
    const model = progressModel(progress.record, now());
    panel.innerHTML = renderProgressPanel(model, pipelineModel(progress.record, now()));
    if (model.title !== announced) { announced = model.title; live.textContent = model.title; }
  };
  const tick = () => {
    const model = progressModel(progress.record, now());
    const el = panel.querySelector('[data-elapsed]');
    if (el) el.textContent = duration(model.elapsedMs);
    const step = panel.querySelector('[data-live-step]');
    const since = pipelineModel(progress.record, now()).activeSince;
    if (step && finite(since)) step.textContent = duration(now() - since);
  };
  const timer = setTimer(tick, 1000);
  draw();
  return {
    record: progress.record,
    update(p) { if (progress.update(p)) draw(); },
    finish(outcome, result) { clearTimer(timer); progress.finish(outcome, result); draw(); return progress.record; },
    destroy() { clearTimer(timer); },
  };
}
