// Cascade chat: one conversation surface, a collapsible conversation sidebar (top left) and a profile menu
// (top right). The profile and portfolio are created at sign-up and stored in this browser.
// Agent mode calls the deployed backend (agent-api.js); Offline mode answers from saved data (chat-answer.js).
import { CORE_TICKERS, TICKER_INFO } from './config.js';
import { escapeHTML as esc, shortTicker, sourceURL, finite, number } from './formatters.js';
import { createWorkspaceStore, PERSONAS, validateHoldings, splitEvenly } from './workspace-store.js';
import { loadSnapshot } from './api.js';
import { askBackend, agentConfigured } from './agent-api.js';
import { answerLocally, suggestions } from './chat-answer.js';
import { createChatStore, getAccount, createAccount, deleteAccount } from './chat-store.js';

const $ = s => document.querySelector(s);
const storage = (() => { try { return globalThis.localStorage; } catch { return null; } })();
const store = createWorkspaceStore(storage);
const chats = createChatStore(storage);
const narrow = matchMedia('(max-width: 800px)');
const state = { chatId: null, mode: 'offline', request: null, tables: null, evidence: null };
const pref = (k, v) => { try { if (v === undefined) return storage?.getItem(k); storage?.setItem(k, v); } catch { return null; } };

// ---------- data ----------
const dataReady = (async () => {
  const [tables, evidence] = await Promise.allSettled([
    loadSnapshot(),
    fetch('./evidence-preview.json').then(r => (r.ok ? r.json() : Promise.reject(Error(`HTTP ${r.status}`)))),
  ]);
  state.tables = tables.status === 'fulfilled' ? tables.value : null;
  state.evidence = evidence.status === 'fulfilled' ? evidence.value : null;
})();

// ---------- small helpers ----------
const initials = name => name.trim().split(/\s+/).slice(0, 2).map(w => w[0]?.toUpperCase() ?? '').join('') || '?';
const prose = text => esc(text).split(/\n{2,}/).map(p => `<p>${p.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>')}</p>`).join('');
const portfolioName = ws => (ws.portfolio === 'custom' ? ws.custom?.name || 'My portfolio' : `${PERSONAS[ws.portfolio].name} · sample`);
function greeting() {
  const h = new Date().getHours();
  return h < 5 ? 'Good evening' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
}

// ---------- sidebar ----------
function setSidebar(open, remember = true) {
  $('#app').dataset.sidebar = open ? 'open' : 'closed';
  $('#sb-open').setAttribute('aria-expanded', String(open));
  $('#scrim').hidden = !(open && narrow.matches);
  if (remember && !narrow.matches) pref('cascade.sidebar', open ? 'open' : 'closed');
}
function renderChatList() {
  const list = chats.list();
  $('#chat-list').innerHTML = list.length ? list.map(c => `<div class="chat-item${c.id === state.chatId ? ' active' : ''}">
      <button type="button" class="chat-link" data-chat="${esc(c.id)}"${c.id === state.chatId ? ' aria-current="page"' : ''}>${esc(c.title)}</button>
      <button type="button" class="chat-del" data-delete="${esc(c.id)}" aria-label="Delete “${esc(c.title)}”" title="Delete">
        <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 5l10 10M15 5L5 15"/></svg></button></div>`).join('')
    : '<p class="sb-empty">Your conversations will appear here.</p>';
}

// ---------- mode ----------
function setMode(mode) {
  state.mode = mode === 'agent' && agentConfigured() ? 'agent' : 'offline';
  pref('cascade.mode', state.mode);
  $('#mode-label').textContent = state.mode === 'agent' ? 'Cascade Agent' : 'Cascade Offline';
  document.querySelectorAll('[data-mode]').forEach(b => b.setAttribute('aria-checked', String(b.dataset.mode === state.mode)));
  const agentBtn = $('[data-mode="agent"]');
  agentBtn.disabled = !agentConfigured();
  $('#agent-option-note').textContent = agentConfigured() ? 'Investigates with tools on the backend' : 'Not connected: no backend endpoint is configured';
  $('#agent-status').innerHTML = agentConfigured()
    ? '<i class="dot on"></i>Agent endpoint configured'
    : '<i class="dot"></i>Agent not connected · offline answers only';
}

// ---------- menus ----------
function toggleMenu(button, menu, open = menu.hidden) {
  document.querySelectorAll('.menu').forEach(m => { if (m !== menu) m.hidden = true; });
  document.querySelectorAll('[aria-haspopup="menu"]').forEach(b => { if (b !== button) b.setAttribute('aria-expanded', 'false'); });
  menu.hidden = !open;
  button.setAttribute('aria-expanded', String(open));
  if (open) menu.querySelector('button:not([disabled])')?.focus();
}
document.addEventListener('click', e => {
  if (!e.target.closest('.mode, .profile')) document.querySelectorAll('.menu').forEach(m => { m.hidden = true; });
});
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  const open = [...document.querySelectorAll('.menu')].find(m => !m.hidden);
  if (open) { open.hidden = true; open.parentElement.querySelector('[aria-haspopup]')?.focus(); }
  else if (narrow.matches && $('#app').dataset.sidebar === 'open') setSidebar(false);
});

// ---------- profile header ----------
function renderProfile() {
  const ws = store.get();
  $('#profile-btn').textContent = initials(ws.profile.name);
  $('#profile-btn').setAttribute('aria-label', `Profile: ${ws.profile.name}`);
  $('#pm-name').textContent = ws.profile.name;
  $('#pm-portfolio').textContent = `${portfolioName(ws)} · ${ws.profile.experience === 'expert' ? 'Expert' : 'Beginner'}`;
}

// ---------- thread ----------
function renderAssistant(m) {
  if (m.kind === 'error') return `<div class="msg assistant"><div class="msg-body error">${prose(m.text)}</div></div>`;
  const tag = m.kind === 'agent' ? 'Agent' : 'Offline · saved data · no AI';
  const steps = m.kind === 'agent'
    ? (m.toolCalls ?? []).map(c => ({ name: c.name || 'Tool call', detail: [c.input, c.output] }))
    : (m.steps ?? []).map(s => ({ name: s }));
  const stepsHTML = steps.length ? `<details class="steps"><summary>${steps.length} step${steps.length > 1 ? 's' : ''}</summary><ol>${steps.map(s => `<li>${esc(s.name)}${s.detail ? `<pre>${esc(JSON.stringify(s.detail[0] ?? {}, null, 2))}</pre><pre>${esc(typeof s.detail[1] === 'string' ? s.detail[1] : JSON.stringify(s.detail[1] ?? null, null, 2))}</pre>` : ''}</li>`).join('')}</ol></details>` : '';
  const body = m.kind === 'agent' ? `<div class="agent-text">${esc(m.answer)}</div>` : prose(m.text);
  const table = m.table ? `<div class="tbl"><table><thead><tr>${m.table.head.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${m.table.rows.map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : '';
  const quotes = (m.quotes ?? []).map(q => `<figure class="quote"><blockquote>${esc(q.text)}</blockquote><figcaption><b>${esc(q.ticker)}</b> ${esc(q.issuer)} · ${esc(q.section)} · ${esc(q.id)}, PDF p. ${esc(q.page)}</figcaption></figure>`).join('');
  const cites = m.kind === 'agent' && m.citations?.length ? `<details class="steps"><summary>${m.citations.length} source${m.citations.length > 1 ? 's' : ''}</summary>${m.citations.map(c => {
    const link = sourceURL(c.source_url);
    return `<figure class="quote"><blockquote>${esc(c.text || 'No passage supplied.')}</blockquote><figcaption><b>${esc(c.ticker || '')}</b> ${esc(c.section || '')}${link ? ` · <a href="${esc(link)}" target="_blank" rel="noopener noreferrer">source ↗</a>` : ''}</figcaption></figure>`;
  }).join('')}</details>` : '';
  const meta = m.kind === 'agent' && finite(m.durationMs) ? ` · ${number(m.durationMs / 1000, 1)} s` : '';
  return `<div class="msg assistant"><div class="msg-tag"><svg viewBox="0 0 24 32" aria-hidden="true"><path d="M12 1S2 13.5 2 20.5a10 10 0 0 0 20 0C22 13.5 12 1 12 1z"/></svg>${tag}${meta}</div>${stepsHTML}<div class="msg-body">${body}${table}${quotes}${cites}</div></div>`;
}
function renderThread() {
  const chat = state.chatId ? chats.get(state.chatId) : null;
  const ws = store.get();
  if (!chat || !chat.messages.length) {
    $('#thread').innerHTML = `<div class="empty"><h1>${esc(greeting())}, ${esc(ws.profile.name.split(' ')[0])}.</h1>
      <p>Ask where your oil exposure comes from. Your portfolio: <b>${esc(portfolioName(ws))}</b>.</p>
      <div class="chips">${suggestions(ws).map(s => `<button type="button" data-suggest="${esc(s)}">${esc(s)}</button>`).join('')}</div></div>`;
    $('#app').classList.add('is-empty');
    return;
  }
  $('#app').classList.remove('is-empty');
  $('#thread').innerHTML = `<div class="messages">${chat.messages.map(m => (m.role === 'user'
    ? `<div class="msg user"><div class="bubble">${esc(m.text)}</div></div>` : renderAssistant(m))).join('')}</div>`;
  $('#thread').scrollTop = $('#thread').scrollHeight;
}
function pending(text) {
  let el = $('#pending');
  if (!el) {
    el = document.createElement('div');
    el.id = 'pending';
    el.className = 'msg assistant';
    $('#thread .messages')?.append(el);
  }
  el.innerHTML = `<div class="msg-tag thinking"><span class="pulse"></span>${esc(text)}</div>`;
  $('#thread').scrollTop = $('#thread').scrollHeight;
}

// ---------- sending ----------
function busy(on) {
  $('#send').hidden = on;
  $('#stop').hidden = !on;
  $('#composer-input').readOnly = on;
}
async function send(question) {
  question = question.trim();
  if (!question || state.request) return;
  if (!state.chatId || !chats.get(state.chatId)) state.chatId = chats.create().id;
  const id = state.chatId;
  chats.add(id, { role: 'user', text: question });
  renderChatList();
  renderThread();
  const controller = new AbortController();
  state.request = controller;
  busy(true);
  let reply;
  try {
    if (state.mode === 'agent') {
      const ws = store.get();
      if (ws.portfolio === 'custom') throw Error('The deployed agent only knows the three sample portfolios (Robert, Amira, Mateo). Switch to a sample in your portfolio settings, or use Offline mode, which works with your own portfolio.');
      pending('Submitting…');
      const result = await askBackend({ question, persona: ws.portfolio, level: ws.profile.experience, sessionId: chats.get(id)?.sessionId ?? undefined,
        signal: controller.signal,
        onProgress: p => {
          if (p.sessionId) chats.setSession(id, p.sessionId);
          pending({ SUBMITTING: 'Submitting…', PENDING: 'Queued…', RUNNING: 'Investigating…', DONE: 'Writing…' }[p.status] ?? 'Working…');
        } });
      reply = { role: 'assistant', kind: 'agent', answer: result.answer, citations: result.citations ?? [], toolCalls: result.toolCalls ?? [], jobId: result.jobId, durationMs: result.durationMs };
    } else {
      pending('Reading your portfolio and the saved data…');
      await Promise.all([dataReady, new Promise(r => setTimeout(r, 450))]);
      controller.signal.throwIfAborted();
      if (!state.tables) throw Error('The saved data could not be loaded. Serve the frontend folder over local HTTP and reload.');
      reply = { role: 'assistant', kind: 'local', ...answerLocally(question, { tables: state.tables, workspace: store.get(), evidence: state.evidence }) };
    }
  } catch (error) {
    reply = { role: 'assistant', kind: 'error', text: controller.signal.aborted
      ? (state.mode === 'agent' ? 'Stopped waiting. A job already submitted to the backend may still finish.' : 'Stopped.')
      : error.name === 'TimeoutError' ? 'Waiting timed out. The job may still be running; asking again starts a new one.' : error.message || 'Something went wrong.' };
  } finally {
    state.request = null;
    busy(false);
  }
  chats.add(id, reply);
  if (state.chatId === id) renderThread();
  renderChatList();
  $('#composer-input').focus();
}

// ---------- profile & portfolio forms (shared by sign-up and settings) ----------
function profileFields(ws) {
  return `<label class="field">Name<input name="name" required maxlength="60" value="${esc(ws.profile.name === 'Your workspace' ? '' : ws.profile.name)}" placeholder="Your first name" autocomplete="given-name"></label>
    <fieldset class="field"><legend>How should Cascade explain things?</legend><div class="seg">
      <label><input type="radio" name="experience" value="beginner"${ws.profile.experience !== 'expert' ? ' checked' : ''}><span><b>Beginner</b>Plain language</span></label>
      <label><input type="radio" name="experience" value="expert"${ws.profile.experience === 'expert' ? ' checked' : ''}><span><b>Expert</b>Statistics included</span></label>
    </div></fieldset>
    <label class="field">What are you trying to understand?<input name="goal" maxlength="140" value="${esc(ws.profile.goal)}"></label>`;
}
function holdingRow(h) {
  return `<div class="h-row"><select name="ticker" aria-label="Ticker">${CORE_TICKERS.map(t => `<option value="${t}"${t === h.ticker ? ' selected' : ''}>${shortTicker(t)} · ${esc(TICKER_INFO[t].name)}</option>`).join('')}</select>
    <label class="h-weight"><input name="weight" type="number" min="0.01" max="100" step="0.01" value="${(h.weight * 100).toFixed(2).replace(/\.00$/, '')}" aria-label="Weight in percent"><span>%</span></label>
    <button type="button" class="icon-btn" data-remove-row aria-label="Remove holding"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 5l10 10M15 5L5 15"/></svg></button></div>`;
}
function portfolioFields(ws) {
  const custom = ws.custom?.holdings ?? [{ ticker: 'XIU.TO', weight: 0.6 }, { ticker: 'ENB.TO', weight: 0.4 }];
  return `<fieldset class="field"><legend>Start from a sample or enter your own</legend><div class="choices">
      ${Object.entries(PERSONAS).map(([k, p]) => `<label class="choice"><input type="radio" name="portfolio" value="${k}"${ws.portfolio === k ? ' checked' : ''}><span><b>${p.name} · ${esc(p.title)}</b>${esc(p.description)}</span></label>`).join('')}
      <label class="choice"><input type="radio" name="portfolio" value="custom"${ws.portfolio === 'custom' ? ' checked' : ''}><span><b>My own holdings</b>Pick from the ${CORE_TICKERS.length} tickers with saved data.</span></label>
    </div></fieldset>
    <div class="custom-editor"${ws.portfolio === 'custom' ? '' : ' hidden'}>
      <label class="field">Portfolio name<input name="custom_name" maxlength="60" value="${esc(ws.custom?.name ?? 'My portfolio')}"></label>
      <div class="h-rows">${custom.map(holdingRow).join('')}</div>
      <div class="h-tools"><button type="button" class="btn ghost" data-add-row>Add holding</button><button type="button" class="btn ghost" data-split>Split evenly</button><span class="h-total" aria-live="polite"></span></div>
    </div>
    <label class="field">Amount invested (CAD)<input name="capital" type="number" min="1" step="1" value="${ws.capital}"></label>
    <p class="hint">Only tickers with saved historical data can be used, so every answer is backed by numbers.</p>`;
}
function readProfile(form) {
  const f = new FormData(form);
  const name = String(f.get('name') ?? '').trim();
  if (!name) return { error: 'Enter your name.' };
  return { profile: { name, goal: String(f.get('goal') ?? '').trim() || 'Understand my oil exposure', experience: f.get('experience') === 'expert' ? 'expert' : 'beginner' } };
}
function readPortfolio(form) {
  const f = new FormData(form);
  const portfolio = String(f.get('portfolio') ?? '');
  const capital = Number(f.get('capital'));
  if (!(capital > 0)) return { error: 'Enter the amount invested.' };
  if (portfolio !== 'custom') return Object.hasOwn(PERSONAS, portfolio) ? { portfolio, capital } : { error: 'Choose a portfolio.' };
  const holdings = [...form.querySelectorAll('.h-row')].map(r => ({ ticker: r.querySelector('select').value, weight: Math.round(Number(r.querySelector('input').value) * 100) / 10000 }));
  const error = validateHoldings(holdings);
  if (error) return { error };
  return { portfolio, capital, custom: { name: String(f.get('custom_name') ?? '').trim() || 'My portfolio', holdings } };
}
function wireEditor(form) {
  const total = () => {
    const sum = [...form.querySelectorAll('.h-row input')].reduce((s, i) => s + (Number(i.value) || 0), 0);
    const el = form.querySelector('.h-total');
    if (el) { el.textContent = `Total ${sum.toFixed(2).replace(/\.00$/, '')}%`; el.classList.toggle('ok', Math.abs(sum - 100) < 0.005); }
  };
  form.addEventListener('change', e => {
    if (e.target.name === 'portfolio') form.querySelector('.custom-editor').hidden = e.target.value !== 'custom';
    total();
  });
  form.addEventListener('input', total);
  form.addEventListener('click', e => {
    const rows = form.querySelector('.h-rows');
    if (e.target.closest('[data-add-row]') && rows.children.length < CORE_TICKERS.length) {
      const used = new Set([...rows.querySelectorAll('select')].map(s => s.value));
      rows.insertAdjacentHTML('beforeend', holdingRow({ ticker: CORE_TICKERS.find(t => !used.has(t)), weight: 0 }));
    }
    if (e.target.closest('[data-remove-row]') && rows.children.length > 1) e.target.closest('.h-row').remove();
    if (e.target.closest('[data-split]')) splitEvenly(rows.children.length).forEach((w, i) => { rows.children[i].querySelector('input').value = (w * 100).toFixed(2).replace(/\.00$/, ''); });
    total();
  });
  total();
}

// ---------- sign-up ----------
function openSignup() {
  const dlg = $('#signup');
  const ws = store.get();
  let step = 1;
  const draw = () => {
    dlg.innerHTML = `<form method="dialog" class="sheet-form" novalidate>
      <p class="step">Step ${step} of 2</p>
      ${step === 1
        ? `<h2 id="signup-title">Create your profile</h2><p class="sub">Cascade uses it to pitch its answers at the right level. It stays in this browser.</p>${profileFields(ws)}`
        : `<h2 id="signup-title">Add your portfolio</h2><p class="sub">Cascade measures how your holdings have moved with oil prices.</p>${portfolioFields(ws)}`}
      <p class="form-error" role="alert"></p>
      <div class="sheet-actions">${step === 2 ? '<button type="button" class="btn ghost" data-back>Back</button>' : ''}<button type="submit" class="btn primary">${step === 1 ? 'Continue' : 'Start chatting'}</button></div>
    </form>`;
    const form = dlg.querySelector('form');
    if (step === 2) wireEditor(form);
    form.querySelector('[data-back]')?.addEventListener('click', () => { step = 1; draw(); });
    form.addEventListener('submit', e => {
      e.preventDefault();
      const r = step === 1 ? readProfile(form) : readPortfolio(form);
      if (r.error) { form.querySelector('.form-error').textContent = r.error; return; }
      Object.assign(ws, r.profile ? { profile: r.profile } : { portfolio: r.portfolio, capital: r.capital, ...(r.custom ? { custom: r.custom } : {}) });
      if (step === 1) { step = 2; draw(); return; }
      store.replace(ws);
      createAccount(storage);
      dlg.close();
      renderProfile(); renderThread();
      $('#composer-input').focus();
    });
    form.querySelector('input:not([type=radio]), input')?.focus();
  };
  dlg.addEventListener('cancel', e => e.preventDefault());
  draw();
  dlg.showModal();
}

// ---------- settings (profile menu) ----------
function openSettings(tab) {
  const dlg = $('#settings');
  const ws = store.get();
  const draw = () => {
    dlg.innerHTML = `<form method="dialog" class="sheet-form" novalidate>
      <div class="sheet-head"><h2 id="settings-title">Settings</h2><button type="button" class="icon-btn" data-close aria-label="Close"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 5l10 10M15 5L5 15"/></svg></button></div>
      <div class="tabs" role="tablist">${['profile', 'portfolio'].map(t => `<button type="button" role="tab" data-tab="${t}" aria-selected="${t === tab}">${t === 'profile' ? 'Profile' : 'Portfolio'}</button>`).join('')}</div>
      ${tab === 'profile' ? profileFields(ws) : portfolioFields(ws)}
      <p class="form-error" role="alert"></p>
      <div class="sheet-actions"><button type="button" class="btn ghost" data-close>Cancel</button><button type="submit" class="btn primary">Save</button></div>
    </form>`;
    const form = dlg.querySelector('form');
    if (tab === 'portfolio') wireEditor(form);
    form.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', () => dlg.close()));
    form.querySelectorAll('[data-tab]').forEach(b => b.addEventListener('click', () => { tab = b.dataset.tab; draw(); }));
    form.addEventListener('submit', e => {
      e.preventDefault();
      const r = tab === 'profile' ? readProfile(form) : readPortfolio(form);
      if (r.error) { form.querySelector('.form-error').textContent = r.error; return; }
      store.update(next => {
        if (r.profile) next.profile = r.profile;
        else { next.portfolio = r.portfolio; next.capital = r.capital; if (r.custom) next.custom = r.custom; }
      });
      dlg.close();
      renderProfile(); renderThread();
    });
  };
  draw();
  dlg.showModal();
}

function signOut() {
  if (!confirm('Sign out? Your profile, portfolio and conversations will be erased from this browser.')) return;
  state.request?.abort();
  store.reset();
  chats.clear();
  deleteAccount(storage);
  state.chatId = null;
  renderChatList(); renderProfile(); renderThread();
  openSignup();
}

// ---------- events ----------
$('#sb-close').addEventListener('click', () => setSidebar(false));
$('#sb-open').addEventListener('click', () => setSidebar($('#app').dataset.sidebar !== 'open'));
$('#scrim').addEventListener('click', () => setSidebar(false));
const newChat = () => {
  state.request?.abort();
  state.chatId = null;
  renderChatList(); renderThread();
  if (narrow.matches) setSidebar(false);
  $('#composer-input').focus();
};
$('#new-chat').addEventListener('click', newChat);
$('#new-chat-top').addEventListener('click', newChat);
$('#chat-list').addEventListener('click', e => {
  const del = e.target.closest('[data-delete]');
  if (del) {
    chats.remove(del.dataset.delete);
    if (state.chatId === del.dataset.delete) state.chatId = null;
    renderChatList(); renderThread();
    return;
  }
  const link = e.target.closest('[data-chat]');
  if (link) {
    state.request?.abort();
    state.chatId = link.dataset.chat;
    renderChatList(); renderThread();
    if (narrow.matches) setSidebar(false);
  }
});
$('#mode-btn').addEventListener('click', () => toggleMenu($('#mode-btn'), $('#mode-menu')));
document.querySelectorAll('[data-mode]').forEach(b => b.addEventListener('click', () => { setMode(b.dataset.mode); toggleMenu($('#mode-btn'), $('#mode-menu'), false); }));
$('#profile-btn').addEventListener('click', () => toggleMenu($('#profile-btn'), $('#profile-menu')));
document.querySelectorAll('[data-open]').forEach(b => b.addEventListener('click', () => { toggleMenu($('#profile-btn'), $('#profile-menu'), false); openSettings(b.dataset.open); }));
$('#sign-out').addEventListener('click', () => { toggleMenu($('#profile-btn'), $('#profile-menu'), false); signOut(); });
$('#thread').addEventListener('click', e => { const s = e.target.closest('[data-suggest]'); if (s) send(s.dataset.suggest); });
const input = $('#composer-input');
const grow = () => { input.style.height = 'auto'; input.style.height = `${Math.min(input.scrollHeight, 220)}px`; };
input.addEventListener('input', grow);
input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('#composer').requestSubmit(); } });
$('#composer').addEventListener('submit', e => { e.preventDefault(); const q = input.value; input.value = ''; grow(); send(q); });
$('#stop').addEventListener('click', () => state.request?.abort());
narrow.addEventListener('change', () => setSidebar(!narrow.matches && pref('cascade.sidebar') !== 'closed', false));

// ---------- start ----------
setMode(pref('cascade.mode') || (agentConfigured() ? 'agent' : 'offline'));
setSidebar(!narrow.matches && pref('cascade.sidebar') !== 'closed', false);
state.chatId = null; // open on a fresh chat, like other chat apps
renderChatList(); renderProfile(); renderThread();
if (!getAccount(storage)) openSignup();
