import { loadInvestigation } from './api.js';
import { askBackend, agentConfigured } from './agent-api.js';
import { renderAgentAnswer } from './agent-render.js';
import { SHOCKS, ETF_TICKERS, STOCK_TICKERS, isSupported } from './config.js';
import { escapeHTML as esc, hasEstimate, number, shortTicker } from './formatters.js';
import { renderHero, renderField, renderDecomposition, renderScenario,
  renderEvidence, renderExpert, previewExplanation } from './render.js';
import { initWorkspace } from './workspace.js';
import { loadCatalog, searchDocuments } from './library-data.js';
import { searchResults } from './library-render.js';

const $ = selector => document.querySelector(selector);
const state = { ticker: 'XIU.TO', mode: 'beginner', source: 'preview', benchmark: 'brent',
  shock: 30, data: null, request: null, questionRequest: null };
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');
const lastCounts = new Map();
let workspace;
const sessions = new Map();

function cancelQuestion() {
  state.questionRequest?.abort();
  state.questionRequest = null;
  $('#question-form button[type=submit]').disabled = false;
  $('#cancel-question').hidden = true;
  $('#answer').setAttribute('aria-busy', 'false');
}

function newConversation() {
  cancelQuestion();
  sessions.clear();
  $('#answer').replaceChildren();
}

function currentRow() { return state.data?.tables.sensitivities.find(row => row.ticker === state.ticker); }

function syncChatContext() {
  $('#chat-ticker').value = state.ticker;
  const available = state.benchmark === 'brent' && hasEstimate(currentRow());
  $('#chat-context').textContent = `${shortTicker(state.ticker)} · ${state.benchmark === 'brent' ? 'Brent' : 'WTI (no data)'} · returns in CAD · ${available ? state.data.provenance.label : 'statistics unavailable or loading'}.`;
  $('#chat-source-status').textContent = $('#answer-source').value === 'local'
    ? 'Local explanation · not an AI response'
    : $('#answer-source').value === 'documents' ? 'Local source search · not an AI answer'
      : agentConfigured() ? 'Backend agent · endpoints configured' : 'Backend agent · not connected';
}

// Rolls numbers from their previous value to the already-rendered final value.
function animateCounts(root) {
  root.querySelectorAll('[data-count]').forEach(element => {
    const key = element.dataset.count, to = Number(element.dataset.value);
    const digits = Number(element.dataset.digits), suffix = element.dataset.suffix || '';
    const from = lastCounts.get(key) ?? 0;
    lastCounts.set(key, to);
    if (reduceMotion.matches || !Number.isFinite(to) || from === to) return;
    const start = performance.now(), duration = 650;
    const tick = now => {
      const t = Math.min(1, (now - start) / duration), eased = 1 - (1 - t) ** 3;
      element.textContent = `${number(from + (to - from) * eased, digits, true)}${suffix}`;
      if (t < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}

const FIELD_ORDER = [...ETF_TICKERS, ...STOCK_TICKERS];
function drawField() { renderField($('#field'), state.data?.tables, FIELD_ORDER, state.ticker); }

function render() {
  syncChatContext();
  const row = currentRow();
  if (!hasEstimate(row)) return;
  const { tables, provenance } = state.data;
  const short = shortTicker(state.ticker);
  $('#source-badge').innerHTML = `<i aria-hidden="true"></i>${esc(provenance.label)}`;
  $('#source-note').textContent = provenance.description;
  $('#coverage-value').textContent = provenance.coverage;
  $('#verified-value').textContent = provenance.verified;
  renderHero($('#headline'), row, state.mode === 'expert', tables.confidence.find(item => item.ticker === state.ticker));
  drawField();
  renderDecomposition($('#decomposition'), tables, state.ticker);
  renderScenario($('#scenario-result'), tables, state.ticker, state.shock, state.source);
  renderEvidence($('#evidence'), $('#evidence-count'), tables, state.ticker);
  $('#expert-section').hidden = state.mode !== 'expert';
  renderExpert($('#expert-section'), tables, row);
  $('#question').placeholder = `Where could ${short}’s oil exposure come from?`;
  document.title = workspace?.isHome() ? 'My workspace — Cascade' : `${short} and oil — Cascade`;
  workspace?.refreshResearchActions();
  animateCounts(document);
}

function showStatus(title, message, { loading = false, retry = false } = {}) {
  $('#research').hidden = true;
  $('#research').setAttribute('aria-busy', String(loading));
  $('#headline').replaceChildren();
  $('#status').innerHTML = `${loading ? '<div class="loader" aria-hidden="true"><i></i><i></i><i></i></div>' : ''}<h1>${esc(title)}</h1><p>${esc(message)}</p>${retry ? '<button type="button" class="ink-button" id="retry-load">Try again</button>' : ''}`;
  $('#retry-load')?.addEventListener('click', load);
}

function resetInvestigation() {
  newConversation();
  $('#answer').replaceChildren();
  $('#question-form button[type=submit]').disabled = false;
}

async function load() {
  state.request?.abort();
  resetInvestigation();
  state.data = null;
  syncChatContext();
  workspace?.refreshResearchActions();
  drawField();
  $('#coverage-value').textContent = 'Not available';
  $('#verified-value').textContent = 'Not verified';
  $('#source-badge').innerHTML = `<i aria-hidden="true"></i>${state.source === 'preview' ? 'Local preview' : 'Backend · not connected'}`;
  $('#source-note').textContent = state.source === 'preview' ? 'Local preview selected. No live AWS connection.' : 'No live results loaded. Preview data will not be substituted.';
  if (state.benchmark !== 'brent') {
    showStatus('No WTI data yet.', 'The data contract only models Brent. Switch back to Brent crude to continue; no WTI numbers have been substituted.'); return;
  }
  const controller = new AbortController();
  state.request = controller;
  showStatus(`Opening ${shortTicker(state.ticker)}…`, `Loading from ${state.source === 'preview' ? 'the local notebook snapshot' : 'the configured backend'}.`, { loading: true });
  try {
    const data = await loadInvestigation({ ticker: state.ticker, mode: state.source, signal: controller.signal });
    if (controller.signal.aborted) return;
    state.data = data;
    if (!hasEstimate(currentRow())) {
      drawField();
      showStatus(`No usable estimate for ${shortTicker(state.ticker)}.`, 'A valid beta, range and sample size weren’t supplied. Pick another ticker or try again. Nothing has been made up to fill the gap.', { retry: true });
      return;
    }
    $('#status').replaceChildren();
    render();
    $('#research').hidden = false;
    $('#research').setAttribute('aria-busy', 'false');
  } catch (error) {
    if (controller.signal.aborted) return;
    const message = error.name === 'TimeoutError' ? 'The request timed out. Try again.'
      : globalThis.location.protocol === 'file:' ? 'Serve this folder over local HTTP so the browser can load the modules and data.'
      : error.message || 'The data could not be loaded.';
    showStatus('That didn’t load.', message, { retry: true });
  }
}

function selectTicker(ticker, { scroll = true } = {}) {
  if (ticker === state.ticker || !isSupported(ticker)) return;
  state.ticker = ticker;
  const canSwap = state.source === 'preview' && state.benchmark === 'brent' && hasEstimate(currentRow());
  if (!canSwap) { load(); return; }
  resetInvestigation();
  render();
  if (scroll && innerWidth < 900) $('#headline').scrollIntoView({ behavior: reduceMotion.matches ? 'auto' : 'smooth', block: 'start' });
}

$('#field').addEventListener('click', event => {
  const button = event.target.closest('[data-ticker]');
  if (button) selectTicker(button.dataset.ticker);
});
$('#source-select').addEventListener('change', event => { state.source = event.target.value; load(); });
$('#benchmark-select').addEventListener('change', event => { state.benchmark = event.target.value; load(); });
document.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click', () => {
  newConversation();
  state.mode = button.dataset.mode;
  workspace?.saveExperience(state.mode);
  document.querySelectorAll('[data-mode]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  if (hasEstimate(currentRow())) render();
}));
document.querySelectorAll('[data-shock]').forEach(button => button.addEventListener('click', () => {
  const shock = Number(button.dataset.shock);
  if (!SHOCKS.includes(shock)) return;
  state.shock = shock;
  document.querySelectorAll('[data-shock]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  if (state.data) { renderScenario($('#scenario-result'), state.data.tables, state.ticker, shock, state.source); animateCounts($('#scenario-result')); }
}));

const dialog = $('#method-dialog');
document.querySelectorAll('#method-open, [data-open-method]').forEach(button => button.addEventListener('click', () => dialog.showModal()));
$('#method-close').addEventListener('click', () => dialog.close());
dialog.addEventListener('click', event => {
  const box = dialog.getBoundingClientRect();
  if (event.target === dialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) dialog.close();
});

$('#chat-ticker').innerHTML = [...ETF_TICKERS, ...STOCK_TICKERS].map(ticker => `<option value="${esc(ticker)}">${esc(shortTicker(ticker))}</option>`).join('');
$('#chat-ticker').value = state.ticker;
$('#chat-ticker').addEventListener('change', event => selectTicker(event.target.value, { scroll: false }));
$('#chat-open').addEventListener('click', () => {
  $('#ask').scrollIntoView({ behavior: 'instant', block: 'start' });
  $('#question').focus({ preventScroll: true });
});

document.querySelectorAll('[data-question]').forEach(button => button.addEventListener('click', () => {
  $('#question').value = button.dataset.question;
  $('#question-form').requestSubmit();
}));
$('#question-form').addEventListener('submit', async event => {
  event.preventDefault();
  const question = $('#question').value.trim();
  const row = currentRow();
  if (!question) return;
  cancelQuestion();
  const turn = document.createElement('article');
  turn.className = 'agent-turn';
  const heading = document.createElement('h3');
  heading.textContent = question;
  const response = document.createElement('div');
  turn.append(heading, response);
  $('#answer').append(turn);
  while ($('#answer').children.length > 10) $('#answer').firstElementChild.remove();
  if ($('#answer-source').value === 'local') {
    if (state.benchmark !== 'brent' || !hasEstimate(row)) {
      response.innerHTML = '<p class="answer-label">Local explanation unavailable</p><p>No usable Brent statistics are loaded for this ticker. Choose Brent and Local preview in Research, or retry the data request.</p>';
      return;
    }
    response.innerHTML = `<p class="answer-label">Local explanation · ${esc(state.data.provenance.label)} · not an AI response</p><p>${esc(previewExplanation(question, row, state.data.tables))}</p>`;
    return;
  }
  const controller = new AbortController();
  state.questionRequest = controller;
  const button = $('#question-form button[type=submit]');
  button.disabled = true;
  $('#cancel-question').hidden = false;
  $('#answer').setAttribute('aria-busy', 'true');
  const context = { persona: $('#agent-persona').value, level: state.mode, ticker: state.ticker };
  const sessionKey = `${context.persona}:${context.level}:${context.ticker}`;
  try {
    if ($('#answer-source').value === 'documents') {
      response.innerHTML = '<p class="answer-label">Searching local source text…</p><p>Exact phrase search across the acquired library. Research targets do not establish membership in the selected ETF.</p>';
      const catalog = await loadCatalog({ signal: controller.signal });
      const found = await searchDocuments(catalog, question, { signal: controller.signal });
      if (controller.signal.aborted) return;
      response.innerHTML = '<p class="answer-label">Local document search · all research sources · no AI call</p>' + searchResults(found, 0, 8)
        + (found.hits.length > 8 ? '<p>Showing the first 8 matching pages. Use the library to browse all matches.</p><button type="button" data-open-library class="ghost-button">Open source library</button>' : '');
      return;
    }
    const result = await askBackend({ question: `Investigating ${context.ticker} against Brent (returns in CAD). ${question}`,
      persona: context.persona, level: context.level, sessionId: sessions.get(sessionKey), signal: controller.signal,
      onProgress: progress => {
        if (controller.signal.aborted) return;
        if (progress.sessionId) sessions.set(sessionKey, progress.sessionId);
        const label = { SUBMITTING: 'Submitting question…', PENDING: 'Queued · waiting for the worker…', RUNNING: 'Investigating · gathering calculations and evidence…', DONE: 'Answer received.', FAILED: 'Backend job failed.' }[progress.status];
        response.innerHTML = `<p class="answer-label">${esc(label)}</p>${progress.jobId ? `<p class="note">Job ${esc(progress.jobId)}</p>` : ''}`;
      },
    });
    if (controller.signal.aborted) return;
    renderAgentAnswer(response, result, context);
  } catch (error) {
    if (!controller.signal.aborted) response.innerHTML = `<p class="answer-label">No answer received</p><p>${esc(error.name === 'TimeoutError' ? 'Waiting timed out. A submitted job may still be running; submitting again creates a new job.' : error.message || 'The answer could not be loaded.')}</p>`;
    else response.innerHTML = $('#answer-source').value === 'documents'
      ? '<p class="note">Local source search stopped.</p>'
      : '<p class="note">Stopped waiting locally. This does not cancel a submitted backend job.</p>';
  } finally {
    if (state.questionRequest === controller) cancelQuestion();
  }
});

$('#cancel-question').addEventListener('click', cancelQuestion);
$('#new-conversation').addEventListener('click', newConversation);
$('#agent-persona').addEventListener('change', newConversation);
$('#answer-source').addEventListener('change', () => { newConversation(); syncChatContext(); });
$('#agent-connection').textContent = `${agentConfigured() ? 'Chat endpoints configured; deployment and data provenance unverified.' : 'Chat API unconfigured. No backend requests can be sent.'} Local explanations use displayed table data without an AI call. Backend chat uses the selected sample portfolio, not a custom mix. Ask self-contained questions: the current agent has no conversation-history store. Only questions and the selected persona/level are sent; your local profile is not uploaded.`;

function applyMode(mode) {
  newConversation();
  state.mode = mode === 'expert' ? 'expert' : 'beginner';
  document.querySelectorAll('[data-mode]').forEach(item => item.setAttribute('aria-pressed', String(item.dataset.mode === state.mode)));
  if (hasEstimate(currentRow())) render();
}

workspace = initWorkspace({
  getInvestigation: () => state,
  setMode: applyMode,
  openInvestigation: settings => {
    if (isSupported(settings.ticker)) state.ticker = settings.ticker;
    if (['preview', 'api'].includes(settings.source)) state.source = settings.source;
    if (SHOCKS.includes(settings.shock)) state.shock = settings.shock;
    state.benchmark = 'brent';
    $('#source-select').value = state.source;
    $('#benchmark-select').value = 'brent';
    document.querySelectorAll('[data-shock]').forEach(button => button.setAttribute('aria-pressed', String(Number(button.dataset.shock) === state.shock)));
    if (settings.mode) applyMode(settings.mode);
    load();
    $('#pick').scrollIntoView({ behavior: 'instant', block: 'start' });
  },
});
load();
