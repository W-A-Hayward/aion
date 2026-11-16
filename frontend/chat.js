// AION chat: one conversation surface, a collapsible conversation sidebar (top left) and a profile menu
// (top right). The profile and portfolio are created at sign-up and stored in this browser.
// Every question goes to the deployed agent (agent-api.js); there is no offline answer mode.
import { CORE_TICKERS, TICKER_INFO } from './config.js';
import { escapeHTML as esc, shortTicker, sourceURL, finite, number } from './formatters.js';
import { createWorkspaceStore, PERSONAS, validateHoldings, splitEvenly } from './workspace-store.js';
import { createRouter, openSource, ensureLibrary } from './views.js';
import { mountStatistics } from './stats-view.js';
import { renderPortfolioPage, snapshotPortfolio, useSaved } from './portfolio-view.js';
import { askBackend, agentConfigured } from './agent-api.js';
import { createChatStore, getAccount, createAccount, deleteAccount } from './chat-store.js';
import { createAuth } from './auth.js';
import { createUserDataClient, createSyncQueue, scopedStorage } from './cloud-sync.js';
import { mountProgress, renderInvestigationSteps } from './investigation-progress.js';
import { renderMarkdown } from './safe-markdown.js';
import { attachMeasuredTips } from './measured-tip.js';
import { compactData, renderAnswerData } from './answer-data.js';
import { toolQuestion, portfolioSnapshot, searchChats, paletteResults, chatToMarkdown, tickerOptions, EVIDENCE_TOPICS, SHIELDS, RATE_MOVES, PROTECTION_ASKS, suggestions } from './chat-tools.js';

const $ = s => document.querySelector(s);
const storage = (() => { try { return globalThis.localStorage; } catch { return null; } })();
let store = createWorkspaceStore(storage);
let chats = createChatStore(storage);
const narrow = matchMedia('(max-width: 800px)');
const state = { chatId: null, mode: 'agent', request: null, tables: null, query: '',
  tool: { tab: 'shock', kind: 'oil', shock: -30, bp: 100, target: '', ticker: 'XIU.TO', ask: 'reliable', topic: 'diesel', pask: 'bonds', shield: 'GLD' } };
const pref = (k, v) => { try { if (v === undefined) return storage?.getItem(k); storage?.setItem(k, v); } catch { return null; } };

// ---------- data ----------
// Only the sample portfolios' composition is read locally (for the portfolio card); answers come from the agent.


// ---------- accounts (Cognito username + password; data saved by lambdas/userdata) ----------
// Without config.auth/userDataUrl the app keeps the profile, portfolio and conversations in this browser only.
const auth = createAuth();
const account = { cloud: null, sync: null, scoped: null };
const signedIn = () => Boolean(account.cloud);
const syncWorkspace = () => account.sync?.schedule('workspace');
const syncChat = id => { if (id) account.sync?.schedule(`chat:${id}`); };
const syncDelete = id => account.sync?.schedule(`delete:${id}`);

function setSyncStatus(s) {
  const el = $('#sync-status');
  if (!el) return;
  el.hidden = !signedIn();
  el.dataset.state = s;
  el.textContent = { saving: 'Saving to your account…', saved: 'Saved to your account', error: 'Couldn’t save · retrying', loading: 'Loading your account…' }[s] ?? '';
}
function renderAccount() {
  const on = auth.configured(), s = auth.session();
  $('#pm-account').hidden = !(on && s);
  $('#pm-account').textContent = s ? `Signed in as ${s.username}` : '';
  $('#change-password').hidden = !(on && s);
  $('#delete-account').hidden = !(on && s);
  $('#sign-out').textContent = on ? 'Sign out' : 'Reset local workspace';
  $('#sign-out').hidden = on && !s;
  setSyncStatus(signedIn() ? $('#sync-status')?.dataset.state || 'saved' : '');
}
async function startSession({ isNew = false } = {}) {
  const s = auth.session();
  account.scoped = scopedStorage(storage, `aion.user.${s.sub}`);
  store = createWorkspaceStore(account.scoped);
  chats = createChatStore(account.scoped);
  account.cloud = createUserDataClient(() => auth.idToken());
  account.sync = createSyncQueue({ client: account.cloud, getWorkspace: () => store.get(), getChat: id => chats.get(id), onStatus: setSyncStatus });
  state.chatId = null;
  renderAccount(); renderChatList(); renderProfile(); renderThread();
  setSyncStatus('loading');
  try {
    const me = await account.cloud.me();
    if (me.workspace) store.replace(me.workspace); else syncWorkspace();
    for (const id of chats.merge(me.chats)) syncChat(id);
    setSyncStatus('saved');
  } catch (error) {
    if (error.code === 'SignedOut') { await endSession(); renderAccount(); openLogin(error.message); return; }
    setSyncStatus('error');
    toast('Couldn’t load your account. Showing what this browser saved.');
  }
  renderChatList(); renderProfile(); renderThread();
  if (isNew) openSignup();
}
async function endSession() {
  await account.sync?.flush().catch(() => {});
  account.scoped?.clearAll();
  Object.assign(account, { cloud: null, sync: null, scoped: null });
  store = createWorkspaceStore(storage);
  chats = createChatStore(storage);
  setSyncStatus('');
}
async function openChat(id) {
  router.show('agent');
  state.request?.abort();
  state.chatId = id;
  renderChatList(); renderThread();
  if (narrow.matches) setSidebar(false);
  if (!chats.get(id)?.remote || !account.cloud) return;
  $('#thread').innerHTML = '<div class="messages"><p class="loading-chat" role="status">Loading conversation…</p></div>';
  try {
    chats.replace(await account.cloud.chat(id));
  } catch (error) {
    toast(error.status === 404 ? 'That conversation no longer exists.' : 'Couldn’t load that conversation. Try again.');
    if (error.status === 404) { chats.remove(id); if (state.chatId === id) state.chatId = null; }
  }
  if (state.chatId === id || state.chatId === null) { renderChatList(); renderThread(); }
}
function openLogin(message = '') {
  const dlg = $('#login');
  let mode = 'signin';
  const draw = (error = '') => {
    dlg.innerHTML = `<form class="sheet-form auth-form" novalidate>
      <div class="auth-brand"><span class="auth-mark" aria-hidden="true"></span><div class="auth-name"><b>AION</b><small>Autonomous Intelligence &amp; Observation Network</small></div></div>
      <div class="tabs" role="tablist">${[['signin', 'Sign in'], ['signup', 'Create account']].map(([k, l]) => `<button type="button" role="tab" data-auth-tab="${k}" aria-selected="${k === mode}">${l}</button>`).join('')}</div>
      <h2 id="login-title">${mode === 'signin' ? 'Welcome back' : 'Create your account'}</h2>
      <p class="sub">${mode === 'signin' ? 'Sign in to find your conversations, profile and portfolio on any device.' : 'Choose a username and a password of at least 8 characters. No email needed.'}</p>
      <label class="field">Username<input name="username" autocomplete="username" autocapitalize="none" spellcheck="false" required minlength="3" maxlength="32"></label>
      <label class="field">Password<span class="pw"><input name="password" type="password" autocomplete="${mode === 'signin' ? 'current-password' : 'new-password'}" required minlength="8" maxlength="256"><button type="button" class="pw-toggle" data-pw aria-pressed="false">Show</button></span></label>
      ${mode === 'signup' ? '<p class="hint">Keep your password somewhere safe: without an email address, a forgotten password can’t be reset.</p>' : ''}
      <p class="form-error" role="alert">${esc(error || message)}</p>
      <div class="sheet-actions"><button type="submit" class="btn primary">${mode === 'signin' ? 'Sign in' : 'Create account'}</button></div>
    </form>`;
    message = '';
    const form = dlg.querySelector('form');
    form.querySelectorAll('[data-auth-tab]').forEach(b => b.addEventListener('click', () => { mode = b.dataset.authTab; draw(); }));
    form.querySelector('[data-pw]').addEventListener('click', e => {
      const pw = form.querySelector('[name=password]'), show = pw.type === 'password';
      pw.type = show ? 'text' : 'password';
      e.currentTarget.textContent = show ? 'Hide' : 'Show';
      e.currentTarget.setAttribute('aria-pressed', String(show));
    });
    form.addEventListener('submit', async e => {
      e.preventDefault();
      const username = form.username.value.trim(), password = form.password.value;
      const button = form.querySelector('[type=submit]');
      button.disabled = true; button.textContent = mode === 'signin' ? 'Signing in…' : 'Creating account…';
      try {
        await (mode === 'signin' ? auth.signIn(username, password) : auth.signUp(username, password));
        dlg.close();
        await startSession({ isNew: mode === 'signup' });
        if (mode === 'signin') toast(`Welcome back, ${username}`);
      } catch (error) {
        draw(error.message || 'Sign-in failed. Try again.');
        dlg.querySelector('[name=username]').value = username;
        dlg.querySelector(error.code === 'UsernameExistsException' ? '[name=username]' : '[name=password]').focus();
      }
    });
    form.querySelector('[name=username]').focus();
  };
  dlg.oncancel = e => e.preventDefault();
  // Escape can still close a modal dialog in some browsers: reopen it while nobody is signed in.
  dlg.onclose = () => { if (auth.configured() && !auth.session()) setTimeout(() => { if (!dlg.open) dlg.showModal(); }, 0); };
  draw();
  if (!dlg.open) dlg.showModal();
}
function openChangePassword() {
  const dlg = $('#password-dialog');
  dlg.innerHTML = `<form class="sheet-form" novalidate>
    <div class="sheet-head"><h2 id="password-title">Change password</h2><button type="button" class="icon-btn" data-close aria-label="Close"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 5l10 10M15 5L5 15"/></svg></button></div>
    <label class="field">Current password<input name="current" type="password" autocomplete="current-password" required></label>
    <label class="field">New password<input name="next" type="password" autocomplete="new-password" required minlength="8"></label>
    <p class="hint">At least 8 characters.</p>
    <p class="form-error" role="alert"></p>
    <div class="sheet-actions"><button type="button" class="btn ghost" data-close>Cancel</button><button type="submit" class="btn primary">Change password</button></div>
  </form>`;
  const form = dlg.querySelector('form');
  form.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', () => dlg.close()));
  form.addEventListener('submit', async e => {
    e.preventDefault();
    try { await auth.changePassword(form.current.value, form.next.value); dlg.close(); toast('Password changed'); }
    catch (error) { form.querySelector('.form-error').textContent = error.code === 'NotAuthorizedException' ? 'The current password is wrong.' : error.message; }
  });
  dlg.showModal();
  form.current.focus();
}
async function deleteAccountFlow() {
  if (!confirm('Delete your account? This permanently erases your conversations, profile and portfolio.')) return;
  try {
    account.sync = null;   // nothing left to save
    await account.cloud.deleteAccount();
    await auth.deleteUser();
  } catch (error) { toast(error.message || 'Couldn’t delete the account. Try again.'); return; }
  await endSession();
  state.chatId = null;
  renderAccount(); renderChatList(); renderProfile(); renderThread();
  openLogin('Your account was deleted.');
}

// ---------- views: agent (landing), statistics, sources, about, my portfolio ----------
let stats = null, aboutLoaded = false;
function renderPortfolio() {
  if (document.body.dataset.view === 'portfolio') $('#portfolio-view').innerHTML = renderPortfolioPage(store.get(), auth.session()?.username ?? null);
}
const router = createRouter({
  onShow(name) {
    document.querySelectorAll('.menu').forEach(m => { m.hidden = true; });
    document.querySelectorAll('[aria-haspopup]').forEach(b => b.setAttribute('aria-expanded', 'false'));
    $('#export-chat').hidden = name !== 'agent' || !(state.chatId && chats.get(state.chatId)?.messages.length);
    if (narrow.matches) setSidebar(false);
    if (name === 'statistics' && !stats) { stats = mountStatistics($('#stats-view')); stats.refresh(); }
    if (name === 'about' && !aboutLoaded) { aboutLoaded = true; import('./quotes.js'); import('./fuel-card.js'); }
    if (name === 'portfolio') renderPortfolio();
    // The library used to start collapsed behind a toggle; as its own view it is simply open.
    if (name === 'sources') ensureLibrary().then(() => { const w = $('#rl-workspace'); if (w) { w.hidden = false; $('#rl-toggle')?.setAttribute('aria-expanded', 'true'); } });
    document.querySelector(`[data-view="${name}"] h1, [data-view="${name}"] h2`)?.setAttribute('tabindex', '-1');
    if (name !== 'agent') $('.views').scrollTop = 0;
  },
});
document.addEventListener('aion:show-source', e => openSource(router, e.detail || {}));

// ---------- small helpers ----------
const initials = name => name.trim().split(/\s+/).slice(0, 2).map(w => w[0]?.toUpperCase() ?? '').join('') || '?';
const prose = text => esc(text).split(/\n{2,}/).map(p => `<p>${p.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>')}</p>`).join('');
const portfolioName = ws => (ws.portfolio === 'custom' ? ws.custom?.name || 'My portfolio' : `${PERSONAS[ws.portfolio].name} · sample`);
const MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
const keyLabel = combo => combo.split('+').map(k => ({ mod: MAC ? '⌘' : 'Ctrl', shift: MAC ? '⇧' : 'Shift', alt: MAC ? '⌥' : 'Alt' }[k] ?? k));
const kbdHTML = combo => keyLabel(combo).map(k => `<kbd>${esc(k)}</kbd>`).join('');
const ICON = {
  logo: '<span class="logo" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="6.8"/><circle cx="17" cy="7.4" r="1.9"/></svg></span>',
  shock: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M11 2.5L4.5 11h5L9 17.5 15.5 9h-5z"/></svg>',
  pie: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 3a7 7 0 1 0 7 7h-7z"/><path d="M12.5 2.6A7 7 0 0 1 17.4 7.5H12.5z"/></svg>',
  gauge: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3.5 14a6.5 6.5 0 1 1 13 0"/><path d="M10 14l3.2-4.2"/></svg>',
  doc: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5.5 2.5h6l3 3v12h-9z"/><path d="M11.5 2.5v3h3M8 10h4.5M8 13h4.5"/></svg>',
  copy: '<svg viewBox="0 0 20 20" aria-hidden="true"><rect x="6.5" y="6.5" width="10" height="10" rx="2"/><path d="M13.5 6.5V5A1.5 1.5 0 0 0 12 3.5H5A1.5 1.5 0 0 0 3.5 5v7A1.5 1.5 0 0 0 5 13.5h1.5"/></svg>',
  retry: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M16 10a6 6 0 1 1-1.8-4.3"/><path d="M16 3.5v3.2h-3.2"/></svg>',
  check: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 10.5l3 3 7-7"/></svg>',
  plus: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 4v12M4 10h12"/></svg>',
  chat: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h9A1.5 1.5 0 0 1 16 5.5v6a1.5 1.5 0 0 1-1.5 1.5H9l-3.5 3v-3h0A1.5 1.5 0 0 1 4 11.5z"/></svg>',
  user: '<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="7" r="3"/><path d="M4.5 16.5a5.5 5.5 0 0 1 11 0"/></svg>',
  sidebar: '<svg viewBox="0 0 20 20" aria-hidden="true"><rect x="2.5" y="3.5" width="15" height="13" rx="2.5"/><path d="M7.5 3.5v13"/></svg>',
  download: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 3.5v9M6.5 9l3.5 3.5L13.5 9"/><path d="M4 13.5v1.5A1.5 1.5 0 0 0 5.5 16.5h9A1.5 1.5 0 0 0 16 15v-1.5"/></svg>',
  bolt: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2.5l1.6 4.4 4.4 1.6-4.4 1.6L10 14.5l-1.6-4.4L4 8.5l4.4-1.6zM15.5 13.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z"/></svg>',
};
let toastTimer;
function toast(text) {
  const el = $('#toast');
  el.textContent = text; el.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { el.hidden = true; }, 2200);
}
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
  const all = chats.list();
  const list = searchChats(all.map(c => chats.get(c.id)), state.query);
  $('#chat-list-label').textContent = state.query ? `${list.length} result${list.length === 1 ? '' : 's'}` : 'Recent';
  $('#export-chat').hidden = !(state.chatId && chats.get(state.chatId)?.messages.length);
  if (state.query && !list.length) { $('#chat-list').innerHTML = '<p class="sb-empty">No conversation matches.</p>'; return; }
  $('#chat-list').innerHTML = list.length ? list.map(c => `<div class="chat-item${c.id === state.chatId ? ' active' : ''}">
      <button type="button" class="chat-link" data-chat="${esc(c.id)}"${c.id === state.chatId ? ' aria-current="page"' : ''}><span class="t">${esc(c.title)}</span>${c.match ? `<span class="m">${esc(c.match)}</span>` : ''}</button>
      <button type="button" class="chat-del" data-delete="${esc(c.id)}" aria-label="Delete “${esc(c.title)}”" title="Delete">
        <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 5l10 10M15 5L5 15"/></svg></button></div>`).join('')
    : '<p class="sb-empty">Your conversations will appear here.</p>';
}

// ---------- mode ----------
function initAgent() {
  $('#app').dataset.mode = 'agent';
  $('#agent-status').innerHTML = agentConfigured()
    ? '<i class="dot on"></i>AION agent on AWS'
    : '<i class="dot"></i>Agent not configured: set submitUrl and statusUrl in config.js';
}

// ---------- menus ----------
function toggleMenu(button, menu, open = menu.hidden) {
  document.querySelectorAll('.menu').forEach(m => { if (m !== menu) m.hidden = true; });
  document.querySelectorAll('[aria-haspopup]').forEach(b => { if (b !== button) b.setAttribute('aria-expanded', 'false'); });
  menu.hidden = !open;
  button.setAttribute('aria-expanded', String(open));
  if (open) menu.querySelector('button:not([disabled])')?.focus();
}
document.addEventListener('click', e => {
  // composedPath: the tools popover re-renders on click, so e.target may already be detached.
  if (!e.composedPath().some(n => n.classList?.contains('mode') || n.classList?.contains('profile') || n.classList?.contains('tools') || n.classList?.contains('palette') || n.dataset?.tool || n.dataset?.quickTool)) {
    document.querySelectorAll('.menu').forEach(m => { m.hidden = true; });
    document.querySelectorAll('[aria-haspopup]').forEach(b => b.setAttribute('aria-expanded', 'false'));
  }
});
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  const open = [...document.querySelectorAll('.menu')].find(m => !m.hidden);
  if (open) { open.hidden = true; const trigger = document.querySelector(`[aria-controls="${open.id}"]`); trigger?.setAttribute('aria-expanded', 'false'); trigger?.focus(); }
  else if (narrow.matches && $('#app').dataset.sidebar === 'open') setSidebar(false);
});

// ---------- profile header ----------
function renderProfile() {
  renderPortfolio();
  const ws = store.get();
  $('#profile-btn').textContent = initials(ws.profile.name);
  $('#profile-btn').setAttribute('aria-label', `Profile: ${ws.profile.name}`);
  $('#pm-name').textContent = ws.profile.name;
  $('#pm-portfolio').textContent = `${portfolioName(ws)} · ${ws.profile.experience === 'expert' ? 'Expert' : 'Beginner'}`;
  $('#portfolio-chip').innerHTML = `<span class="sw" aria-hidden="true"></span>${esc(portfolioName(ws))}`;
  $('#portfolio-chip').setAttribute('aria-label', `Portfolio: ${portfolioName(ws)}. Change portfolio`);
  document.querySelectorAll('[data-level]').forEach(b => b.setAttribute('aria-checked', String(b.dataset.level === (ws.profile.experience === 'expert' ? 'expert' : 'beginner'))));
}

// ---------- thread ----------
const investigation = m => renderInvestigationSteps({ record: m.progress,
  result: { toolCalls: m.toolCalls, trace: m.trace, citations: m.citations, durationMs: m.durationMs } });
const actions = (i, q) => `<div class="msg-actions"><button type="button" class="act" data-act="copy" data-idx="${i}">${ICON.copy}Copy</button>${q ? `<button type="button" class="act" data-act="retry" data-q="${esc(q)}">${ICON.retry}Ask again</button>` : ''}</div>`;
// Agent text: safe Markdown, with the contract's inline markers styled. A leading verdict ("**MINOR.**") is
// dropped from the text when the verdict is shown as a badge.
const TAG_RE = /\[(measured|source|documented|simulated)\]/g;
// The agent ends with a caveat line ("2021–2026 · past behaviour · simulation · not advice"), written in the
// question's language. It is shown once, under the answer, instead of inside the text.
const CAVEAT_LINE = /\n\s*(2021\s*[–-]\s*2026\s*·[^\n]*)\s*$/;
export function splitCaveat(answer) {
  const text = String(answer ?? '');
  const m = text.match(CAVEAT_LINE);
  return m ? { text: text.slice(0, m.index).trimEnd(), caveat: m[1].trim() } : { text, caveat: null };
}
function agentHTML(m) {
  let text = splitCaveat(m.answer).text;
  if (m.verdict) text = text.replace(new RegExp(`^\\s*[*_#>]*\\s*${m.verdict.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}[*_]*\\s*[.:\u2014-]*[*_]*\\s*`, 'i'), '');
  return renderMarkdown(text)
    .replace(TAG_RE, '<span class="ip-tag" data-kind="$1" tabindex="0" aria-label="$1 — how this number was computed">$1</span>')
    .replace(/\[(\d{1,2})\]/g, (all, n) => (m.citations ?? []).some(c => c.n === Number(n))
      ? `<a class="cite-ref" href="#cite-${esc(m.jobId)}-${n}">[${n}]</a>` : all);
}
function renderAssistant(m, i = 0, q = '') {
  // The pipeline only says something once the job reached the backend (it has a job ID).
  if (m.kind === 'error') return `<div class="msg assistant" data-mi="${i}">${m.progress?.jobId ? investigation(m) : ''}<div class="msg-body error">${prose(m.text)}</div>${q ? `<div class="msg-actions"><button type="button" class="act" data-act="retry" data-q="${esc(q)}">${ICON.retry}Try again</button></div>` : ''}</div>`;
  const tag = m.kind === 'agent' ? '<span class="badge agent">Agent</span>' : '<span class="badge">Earlier saved-data answer</span>';
  const local = m.kind === 'agent' ? [] : m.steps ?? [];
  const stepsHTML = m.kind === 'agent' ? investigation(m)
    : local.length ? `<details class="steps"><summary>${local.length} step${local.length > 1 ? 's' : ''}</summary><ol>${local.map(s => `<li>${esc(s)}</li>`).join('')}</ol></details>` : '';
  const body = m.kind === 'agent' ? `<div class="agent-text">${agentHTML(m)}</div>` : prose(m.text);
  const table = m.table ? `<div class="tbl"><table><thead><tr>${m.table.head.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${m.table.rows.map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : '';
  const quotes = (m.quotes ?? []).map(q => `<figure class="quote"><blockquote>${esc(q.text)}</blockquote><figcaption><b>${esc(q.ticker)}</b> ${esc(q.issuer)} · ${esc(q.section)} · ${esc(q.id)}, PDF p. ${esc(q.page)}${q.evidenceId ? ` · <a href="?view=sources" data-go="sources">Open sources</a>` : ''}</figcaption></figure>`).join('');
  // Citations in either shape: contract {n, excerpt, publisher, date, doc_type, trust, url} or older {text, ticker, section, source_url}.
  const cites = m.kind === 'agent' && m.citations?.length ? `<details class="steps"${m.citations.some(c => finite(c.n)) ? ' open' : ''}><summary>${m.citations.length} source${m.citations.length > 1 ? 's' : ''}</summary>${m.citations.map(c => {
    const link = sourceURL(c.url ?? c.source_url);
    const who = [c.publisher, c.date, c.doc_type, c.trust].filter(x => typeof x === 'string' && x).map(esc).join(' · ');
    return `<figure class="quote"${finite(c.n) ? ` id="cite-${esc(m.jobId)}-${c.n}"` : ''}><blockquote>${finite(c.n) ? `<b class="cite-n">[${c.n}]</b> ` : ''}${esc(c.excerpt ?? c.text ?? 'No passage supplied.')}</blockquote><figcaption>${c.ticker ? `<b>${esc(c.ticker)}</b> ` : ''}${who || esc(c.section || '')}${link ? ` · <a href="${esc(link)}" target="_blank" rel="noopener noreferrer">source ↗</a>` : ''}</figcaption></figure>`;
  }).join('')}</details>` : '';
  const meta = m.kind === 'agent' && finite(m.durationMs) ? ` · ${number(m.durationMs / 1000, 1)} s` : '';
  const verdict = m.kind === 'agent' && m.verdict ? `<span class="verdict" data-verdict="${esc(m.verdict.toLowerCase().replace(/\s+/g, '-'))}">${esc(m.verdict)}</span>` : '';
  const refusal = m.kind === 'agent' && m.refusal ? '<p class="refusal-note">AION declined part of this request: it does not give advice, predictions or buy/sell calls.</p>' : '';
  const caveatText = m.kind === 'agent' ? splitCaveat(m.answer).caveat ?? m.caveat : null;
  const caveat = caveatText ? `<p class="caveat">${esc(caveatText)}</p>` : '';
  const dataCard = m.kind === 'agent' && m.data ? renderAnswerData(m.data) : '';

  return `<div class="msg assistant" data-mi="${i}"><div class="msg-tag">${ICON.logo}${tag}${meta}</div>${stepsHTML}<div class="msg-body">${verdict}${refusal}${body}${dataCard}${table}${quotes}${cites}${caveat}</div>${actions(i, q)}</div>`;
}
const BAR_COLORS = ['#4f46e5', '#8b5cf6', '#06b6d4', '#94a3b8', '#cbd5e1'];
function snapshotHTML(ws) {
  const snap = portfolioSnapshot(null, ws);
  if (!snap) return '';
  const shown = snap.top.reduce((t, h) => t + h.weight, 0);
  const parts = [...snap.top, ...(shown < 0.999 ? [{ ticker: 'Other', weight: 1 - shown }] : [])];
  return `<section class="snapshot composition" aria-label="Your portfolio">
    <div class="snap-cell"><p class="snap-k">Portfolio</p><p class="snap-name"><span>${esc(snap.name)}</span><button type="button" data-open-portfolio>Edit</button></p>
      <div class="bars" aria-hidden="true">${parts.map((h, i) => `<i style="flex:${h.weight};background:${BAR_COLORS[i] ?? BAR_COLORS[4]}"></i>`).join('')}</div>
      <p class="legend">${parts.map((h, i) => `<span style="--c:${BAR_COLORS[i] ?? BAR_COLORS[4]}">${esc(h.ticker)} ${Math.round(h.weight * 100)}%</span>`).join('')}</p></div>
    <p class="snapshot-note">Sample and custom portfolios are analysed by the agent from measured weekly data, 2021–2026.</p>
  </section>`;
}
function renderThread() {
  const chat = state.chatId ? chats.get(state.chatId) : null;
  const ws = store.get();
  if (!chat || !chat.messages.length) {
    $('#thread').innerHTML = `<div class="empty">
      <span class="eyebrow"><b>Agent</b>Measured weekly data and cited sources · 2021–2026</span>
      <h1>Portfolio risk research</h1>
      <p class="lede">Check what moved or protected your portfolio in 2021–2026: interest rates, stocks, oil and the dollar. Every number comes from measured weekly data or a cited source.</p>
      <button type="button" class="start-investigation" data-suggest="${esc(PROTECTION_ASKS.bonds)}">Did my bonds protect me? <span aria-hidden="true">↗</span></button>
      <div class="research-trail" aria-label="More"><button type="button" data-go="statistics"><b>01</b> Statistics</button><button type="button" data-go="sources"><b>02</b> Sources</button><button type="button" data-go="about"><b>03</b> How it works</button></div>
      <div class="cards six">${[
        ['protect', ICON.pie, 'What protected you', 'Bonds, cushions and drawdowns in your worst weeks', true, ''],
        ['protect', ICON.gauge, 'Test a shield', 'Gold, bonds or the dollar in the worst weeks', true, 'shield'],
        ['shock', ICON.shock, 'Rates & oil scenarios', 'Rate moves in bp, Brent ±15% or ±30%', false, ''],
        ['ticker', ICON.gauge, 'Beta & uncertainty', 'One ticker’s oil sensitivity and confidence', false, ''],
        ['evidence', ICON.doc, 'Company evidence', 'Original passages from annual reports', false, ''],
        ['exposure', ICON.pie, 'Oil exposure', 'Weighted estimate for your portfolio', false, ''],
      ].map(([k, ico, title, sub, agent, pask], i) => `<button type="button" class="card" data-tool="${k}"${pask ? ` data-pask="${pask}"` : ''} style="--i:${i}"><span class="card-ico">${ico}</span><b>${title}</b><span>${sub}</span></button>`).join('')}</div>
      ${snapshotHTML(ws)}
      <div class="chips">${suggestions().map(s => `<button type="button" data-suggest="${esc(s)}">${esc(s)}</button>`).join('')}</div></div>`;
    $('#app').classList.add('is-empty');
    renderChatList();
    return;
  }
  $('#app').classList.remove('is-empty');
  let lastQ = '';
  $('#thread').innerHTML = `<div class="messages">${chat.messages.map((m, i) => {
    if (m.role === 'user') { lastQ = m.text; return `<div class="msg user"><div class="bubble">${esc(m.text)}</div></div>`; }
    return renderAssistant(m, i, lastQ);
  }).join('')}</div>`;
  $('#thread').scrollTop = $('#thread').scrollHeight;
}
function pendingSlot() {
  let el = $('#pending');
  if (!el) {
    el = document.createElement('div');
    el.id = 'pending';
    el.className = 'msg assistant';
    $('#thread .messages')?.append(el);
  }
  return el;
}
function pending(text) {
  pendingSlot().innerHTML = `<div class="msg-tag thinking"><span class="pulse"></span>${esc(text)}</div>`;
  $('#thread').scrollTop = $('#thread').scrollHeight;
}
// Agent mode: the live investigation panel (investigation-progress.js), fed only by backend job statuses.
function agentProgress() {
  const panel = mountProgress(pendingSlot());
  $('#thread').scrollTop = $('#thread').scrollHeight;
  return {
    ...panel,
    update(p) { panel.update(p); $('#thread').scrollTop = $('#thread').scrollHeight; },
  };
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
  syncChat(id);
  renderChatList();
  renderThread();
  const controller = new AbortController();
  state.request = controller;
  busy(true);
  let reply, progress = null;
  try {
    {
      if (!agentConfigured()) throw Error('The agent is not configured: set submitUrl and statusUrl in config.js.');
      const ws = store.get();
      progress = agentProgress();
      const result = await askBackend({ question, persona: ws.portfolio, level: ws.profile.experience,
        ...(ws.portfolio === 'custom' ? { holdings: ws.custom?.holdings } : {}), sessionId: chats.get(id)?.sessionId ?? undefined,
        signal: controller.signal,
        onProgress: p => {
          if (p.sessionId) chats.setSession(id, p.sessionId);
          if (!controller.signal.aborted) progress.update(p);
        } });
      const meta = result.answerMeta ?? {};
      reply = { role: 'assistant', kind: 'agent', answer: result.answer, verdict: meta.verdict ?? null, caveat: meta.caveat ?? null, refusal: meta.refusal === true,
        citations: result.citations ?? [], toolCalls: result.toolCalls ?? [], jobId: result.jobId ?? result.job_id, durationMs: result.durationMs,
        ...(compactData(result.data) ? { data: compactData(result.data) } : {}),
        ...(Array.isArray(result.trace) ? { trace: result.trace } : {}), progress: progress.finish('done', result) };
    }
  } catch (error) {
    const record = progress?.finish(controller.signal.aborted ? 'stopped' : error.name === 'TimeoutError' ? 'timeout' : 'failed');
    reply = { role: 'assistant', kind: 'error', ...(record ? { progress: record } : {}), text: controller.signal.aborted
      ? 'Stopped waiting. A job already submitted to the backend may still finish.'
      : error.name === 'TimeoutError' ? 'Waiting timed out. The job may still be running; asking again starts a new one.'
      : store.get().portfolio === 'custom' && /HTTP 400/.test(error.message)
        ? 'The deployed agent does not accept your own portfolio yet (its backend update is not deployed). Switch to a sample portfolio (Robert, Amira or Mateo) in your portfolio settings to ask now.'
        : error instanceof TypeError && /fetch|network|load failed/i.test(error.message)
          ? 'Couldn’t reach the agent. Check your connection and try again.'
          : error.message || 'Something went wrong.' };
  } finally {
    state.request = null;
    busy(false);
  }
  chats.add(id, reply);
  syncChat(id);
  if (state.chatId === id) renderThread();
  renderChatList();
  $('#composer-input').focus();
}

// ---------- profile & portfolio forms (shared by sign-up and settings) ----------
function profileFields(ws) {
  return `<label class="field">Name<input name="name" required maxlength="60" value="${esc(ws.profile.name === 'Your workspace' ? '' : ws.profile.name)}" placeholder="Your first name" autocomplete="given-name"></label>
    <fieldset class="field"><legend>How should AION explain things?</legend><div class="seg">
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
  return { profile: { name, goal: String(f.get('goal') ?? '').trim() || 'Understand what moves my portfolio', experience: f.get('experience') === 'expert' ? 'expert' : 'beginner' } };
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
        ? `<h2 id="signup-title">Create your profile</h2><p class="sub">Choose your explanation level. ${signedIn() ? 'It is saved to your account.' : 'Your profile is stored in this browser.'}</p>${profileFields(ws)}`
        : `<h2 id="signup-title">Add your portfolio</h2><p class="sub">AION checks how your holdings moved with interest rates, stocks and oil, and what protected them.</p>${portfolioFields(ws)}`}
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
      syncWorkspace();
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
      <div class="sheet-head"><h2 id="settings-title">Your local workspace</h2><button type="button" class="icon-btn" data-close aria-label="Close"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 5l10 10M15 5L5 15"/></svg></button></div>
      <p class="hint">Stored only in this browser. The portfolio is a research simulation.</p><div class="tabs" role="tablist">${['profile', 'portfolio'].map(t => `<button type="button" role="tab" data-tab="${t}" aria-selected="${t === tab}">${t === 'profile' ? 'Profile' : 'Portfolio'}</button>`).join('')}</div>
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
      syncWorkspace();
      dlg.close();
      renderProfile(); renderThread();
    });
  };
  draw();
  dlg.showModal();
}

async function signOut() {
  if (auth.configured()) {
    if (!confirm('Sign out? Your conversations, profile and portfolio stay saved in your account.')) return;
    state.request?.abort();
    await endSession();
    await auth.signOut();
    state.chatId = null;
    renderAccount(); renderChatList(); renderProfile(); renderThread();
    openLogin();
    return;
  }
  if (!confirm('Reset this local workspace? Your profile, mock portfolio and conversations will be erased from this browser.')) return;
  state.request?.abort();
  store.reset();
  chats.clear();
  deleteAccount(storage);
  state.chatId = null;
  renderChatList(); renderProfile(); renderThread();
}

// ---------- events ----------
$('#sb-close').addEventListener('click', () => setSidebar(false));
$('#sb-open').addEventListener('click', () => setSidebar($('#app').dataset.sidebar !== 'open'));
$('#scrim').addEventListener('click', () => setSidebar(false));
const newChat = () => {
  router.show('agent');
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
    syncDelete(del.dataset.delete);
    if (state.chatId === del.dataset.delete) state.chatId = null;
    renderChatList(); renderThread();
    return;
  }
  const link = e.target.closest('[data-chat]');
  if (link) openChat(link.dataset.chat);
});
$('#profile-btn').addEventListener('click', () => toggleMenu($('#profile-btn'), $('#profile-menu')));
document.querySelectorAll('[data-open]').forEach(b => b.addEventListener('click', () => { toggleMenu($('#profile-btn'), $('#profile-menu'), false); openSettings(b.dataset.open); }));
$('#sign-out').addEventListener('click', () => { toggleMenu($('#profile-btn'), $('#profile-menu'), false); signOut(); });
$('#change-password').addEventListener('click', () => { toggleMenu($('#profile-btn'), $('#profile-menu'), false); openChangePassword(); });
$('#delete-account').addEventListener('click', () => { toggleMenu($('#profile-btn'), $('#profile-menu'), false); deleteAccountFlow(); });
addEventListener('pagehide', () => { account.sync?.flush(); });
$('#thread').addEventListener('click', e => {
  const s = e.target.closest('[data-suggest]');
  if (s) { send(s.dataset.suggest); return; }
  const tool = e.target.closest('[data-tool]');
  if (tool) {
    if (tool.dataset.pask) state.tool.pask = tool.dataset.pask;
    else if (tool.dataset.tool === 'protect') state.tool.pask = state.tool.pask === 'shield' ? 'bonds' : state.tool.pask;
    if (tool.dataset.tool === 'exposure') send(toolQuestion('exposure')); else openTools(tool.dataset.tool);
    return;
  }
  if (e.target.closest('[data-open-portfolio]')) { openSettings('portfolio'); return; }
  const act = e.target.closest('[data-act]');
  if (act?.dataset.act === 'retry') send(act.dataset.q);
  if (act?.dataset.act === 'copy') {
    const m = chats.get(state.chatId)?.messages[Number(act.dataset.idx)];
    const text = m ? (m.kind === 'agent' ? m.answer : m.text).replace(/\*\*(.+?)\*\*/g, '$1') : '';
    navigator.clipboard?.writeText(text).then(() => {
      act.classList.add('done'); act.innerHTML = `${ICON.check}Copied`;
      setTimeout(() => { act.classList.remove('done'); act.innerHTML = `${ICON.copy}Copy`; }, 1600);
    }, () => toast('Copy is blocked in this browser.'));
  }
});
const input = $('#composer-input');
const grow = () => { input.style.height = 'auto'; input.style.height = `${Math.min(input.scrollHeight, 220)}px`; };
input.addEventListener('input', grow);
input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('#composer').requestSubmit(); } });
$('#composer').addEventListener('submit', e => { e.preventDefault(); const q = input.value; input.value = ''; grow(); send(q); });
$('#stop').addEventListener('click', () => state.request?.abort());
narrow.addEventListener('change', () => setSidebar(!narrow.matches && pref('cascade.sidebar') !== 'closed', false));

document.querySelectorAll('[data-quick-tool]').forEach(button => button.addEventListener('click', () => {
  if (narrow.matches) setSidebar(false);
  openTools(button.dataset.quickTool);
}));

// ---------- tools popover ----------
const TOOL_TABS = [['shock', ICON.shock, 'Scenario'], ['ticker', ICON.gauge, 'Beta check'], ['evidence', ICON.doc, 'Evidence'], ['protect', ICON.pie, 'Protection']];
function toolPreview() {
  const t = state.tool;
  try {
    if (t.tab === 'shock') return t.kind === 'rates' ? toolQuestion('rates', { bp: t.bp }) : toolQuestion('shock', { shock: t.shock, ticker: t.target });
    if (t.tab === 'protect') return t.pask === 'shield' ? toolQuestion('shield', { shield: t.shield }) : toolQuestion('protect', { ask: t.pask });
    return toolQuestion(t.tab, t);
  }
  catch (e) { return e.message; }
}
function renderTools() {
  const t = state.tool, opts = tickerOptions();
  const kindSeg = `<div class="seg-mini kind-seg" role="radiogroup" aria-label="Scenario type">${[['oil', 'Oil'], ['rates', 'Interest rates']].map(([k, l]) => `<button type="button" role="radio" data-kind="${k}" aria-checked="${t.kind === k}">${l}</button>`).join('')}</div>`;
  const body = t.tab === 'shock' && t.kind === 'rates'
    ? `<h3>Interest-rate scenario</h3>${kindSeg}<p>Move US and Canadian yields through the measured yield links. A statistical scenario, not a forecast.</p>
       <fieldset class="shock-grid five" aria-label="Rate move">${RATE_MOVES.map(v => `<label><input type="radio" name="bp" value="${v}"${v === t.bp ? ' checked' : ''}><span>${v > 0 ? '+' : '−'}${Math.abs(v)} bp</span></label>`).join('')}</fieldset>`
    : t.tab === 'protect'
      ? `<h3>What protected you</h3><p>Check what actually cushioned your worst weeks in 2021–2026, or test a possible shield.</p>
         <label class="tool-row">Question<select name="pask">${[...Object.entries(PROTECTION_ASKS).map(([k, q]) => [k, q]), ['shield', 'Test a shield…']].map(([k, q]) => `<option value="${k}"${k === t.pask ? ' selected' : ''}>${esc(q)}</option>`).join('')}</select></label>
         ${t.pask === 'shield' ? `<label class="tool-row">Shield<select name="shield">${SHIELDS.map(x => `<option value="${esc(x.value)}"${x.value === t.shield ? ' selected' : ''}>${esc(x.label)}</option>`).join('')}</select></label>` : ''}`
    : t.tab === 'shock'
    ? `<h3>Oil scenario</h3>${kindSeg}<p>Apply a one-week Brent move to saved historical betas. This is a statistical scenario, not a price prediction.</p>
       <fieldset class="shock-grid" aria-label="Brent move">${[-30, -15, 15, 30].map(v => `<label><input type="radio" name="shock" value="${v}"${v === t.shock ? ' checked' : ''}><span>${v > 0 ? '+' : '−'}${Math.abs(v)}%</span></label>`).join('')}</fieldset>
       <label class="tool-row">Apply to<select name="target"><option value="">My portfolio</option>${opts.map(o => `<option value="${o.value}"${o.value === t.target ? ' selected' : ''}>${esc(o.label)}</option>`).join('')}</select></label>`
    : t.tab === 'ticker'
      ? `<h3>Beta check</h3><p>One ticker’s weekly Brent beta, its 95% range and how it held up.</p>
         <label class="tool-row">Ticker<select name="ticker">${opts.map(o => `<option value="${o.value}"${o.value === t.ticker ? ' selected' : ''}>${esc(o.label)}</option>`).join('')}</select></label>
         <label class="tool-row">Question<select name="ask"><option value="beta"${t.ask === 'beta' ? ' selected' : ''}>What is its oil beta?</option><option value="reliable"${t.ask === 'reliable' ? ' selected' : ''}>How reliable is it?</option><option value="why"${t.ask === 'why' ? ' selected' : ''}>Why is it exposed?</option></select></label>`
      : `<h3>Company evidence</h3><p>Search annual-report passages from TSX 60 companies. They describe how oil reaches a business, not which way shares move.</p>
         <div class="topic-grid" role="group" aria-label="Topic">${EVIDENCE_TOPICS.map(x => `<button type="button" data-topic="${esc(x)}" aria-pressed="${x === t.topic}">${esc(x)}</button>`).join('')}</div>`;
  $('#tools-menu').innerHTML = `<div class="tool-tabs" role="tablist">${TOOL_TABS.map(([k, ico, label]) => `<button type="button" role="tab" id="tool-tab-${k}" aria-controls="tool-panel" tabindex="${k === t.tab ? 0 : -1}" data-tab="${k}" aria-selected="${k === t.tab}">${ico}${label}</button>`).join('')}</div>
    <div class="tool-body" id="tool-panel" role="tabpanel" aria-labelledby="tool-tab-${t.tab}">${body}
      <p class="preview" aria-live="polite">${esc(toolPreview())}</p>
      <div class="tool-actions"><button type="button" class="btn ghost sm" data-tool-insert>Edit first</button><button type="button" class="btn primary sm" data-tool-ask>Ask</button></div>
    </div>`;
}
function openTools(tab) {
  if (tab) state.tool.tab = tab;
  renderTools();
  toggleMenu($('#tools-btn'), $('#tools-menu'), true);
  $('#tools-menu [aria-selected=true]')?.focus();
}
$('#tools-btn').addEventListener('click', () => { renderTools(); toggleMenu($('#tools-btn'), $('#tools-menu')); });
$('#tools-menu').addEventListener('click', e => {
  const tab = e.target.closest('[data-tab]');
  if (tab) { state.tool.tab = tab.dataset.tab; renderTools(); $(`#tools-menu [data-tab="${tab.dataset.tab}"]`).focus(); return; }
  const topic = e.target.closest('[data-topic]');
  if (topic) { state.tool.topic = topic.dataset.topic; renderTools(); return; }
  const kind = e.target.closest('[data-kind]');
  if (kind) { state.tool.kind = kind.dataset.kind; renderTools(); $(`#tools-menu [data-kind="${kind.dataset.kind}"]`)?.focus(); return; }
  if (e.target.closest('[data-tool-ask]')) {
    const q = toolPreview();
    toggleMenu($('#tools-btn'), $('#tools-menu'), false);
    send(q);
    return;
  }
  if (e.target.closest('[data-tool-insert]')) {
    input.value = toolPreview(); grow();
    toggleMenu($('#tools-btn'), $('#tools-menu'), false);
    input.focus(); input.setSelectionRange(input.value.length, input.value.length);
  }
});
$('#tools-menu').addEventListener('keydown', e => {
  const tab = e.target.closest('[data-tab]');
  if (!tab || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
  e.preventDefault();
  const current = TOOL_TABS.findIndex(([key]) => key === tab.dataset.tab);
  const next = e.key === 'Home' ? 0 : e.key === 'End' ? TOOL_TABS.length - 1 : (current + (e.key === 'ArrowRight' ? 1 : -1) + TOOL_TABS.length) % TOOL_TABS.length;
  openTools(TOOL_TABS[next][0]);
});
$('#tools-menu').addEventListener('change', e => {
  const { name, value } = e.target;
  if (name === 'shock') state.tool.shock = Number(value);
  if (name === 'target') state.tool.target = value;
  if (name === 'ticker') state.tool.ticker = value;
  if (name === 'ask') state.tool.ask = value;
  if (name === 'bp') state.tool.bp = Number(value);
  if (name === 'shield') state.tool.shield = value;
  if (name === 'pask') { state.tool.pask = value; renderTools(); return; }
  $('#tools-menu .preview').textContent = toolPreview();
});

// ---------- composer chips ----------
$('#portfolio-chip').addEventListener('click', () => openSettings('portfolio'));
document.querySelector('.seg-mini').addEventListener('keydown', e => {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
  e.preventDefault();
  const next = e.key === 'Home' ? 'beginner' : e.key === 'End' ? 'expert' : store.get().profile.experience === 'expert' ? 'beginner' : 'expert';
  const button = $(`[data-level="${next}"]`); button.click(); button.focus();
});
document.querySelectorAll('[data-level]').forEach(b => b.addEventListener('click', () => {
  store.update(next => { next.profile.experience = b.dataset.level; });
  syncWorkspace();
  renderProfile();
  toast(`Explanations: ${b.dataset.level === 'expert' ? 'Expert, statistics included' : 'Beginner, plain language'}`);
}));

// ---------- conversation search ----------
$('#chat-search').addEventListener('input', e => { state.query = e.target.value; renderChatList(); });
$('#chat-search').addEventListener('keydown', e => { if (e.key === 'Escape' && e.target.value) { e.stopPropagation(); e.target.value = ''; state.query = ''; renderChatList(); } });

// ---------- export ----------
function exportChat() {
  const chat = state.chatId && chats.get(state.chatId);
  if (!chat?.messages.length) { toast('Nothing to export yet.'); return; }
  const blob = new Blob([chatToMarkdown(chat)], { type: 'text/markdown' });
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: `${(chat.title || 'conversation').replace(/[^\w\- ]+/g, '').trim().slice(0, 50) || 'conversation'}.md` });
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  toast('Conversation exported as Markdown');
}
$('#export-chat').addEventListener('click', exportChat);

// ---------- command palette ----------
const COMMANDS = () => [
  { id: 'sources', label: 'Go to Sources', icon: ICON.doc, keywords: 'library register documents pages data reports', run: () => router.show('sources') },
  { id: 'statistics', label: 'Go to Statistics', icon: ICON.gauge, keywords: 'beta confidence intervals regression ticker', run: () => router.show('statistics') },
  { id: 'about', label: 'Go to About', icon: ICON.bolt, keywords: 'how it works help agent disclosures', run: () => router.show('about') },
  { id: 'my-portfolio', label: 'My portfolio & saved portfolios', icon: ICON.pie, keywords: 'account saved holdings', run: () => router.show('portfolio') },
  { id: 'new', label: 'New chat', icon: ICON.plus, keys: 'mod+shift+O', run: newChat },
  { id: 'exposure', label: 'Exposure breakdown of my portfolio', icon: ICON.pie, keywords: 'tool beta', run: () => send(toolQuestion('exposure')) },
  { id: 'shock', label: 'Shock simulator', icon: ICON.shock, keywords: 'tool brent scenario stress', run: () => openTools('shock') },
  { id: 'ticker', label: 'Beta check for a ticker', icon: ICON.gauge, keywords: 'tool reliable', run: () => openTools('ticker') },
  { id: 'evidence', label: 'Search company evidence', icon: ICON.doc, keywords: 'tool annual report diesel', run: () => openTools('evidence') },
  { id: 'level', label: `Explain as ${store.get().profile.experience === 'expert' ? 'Beginner' : 'Expert'}`, icon: ICON.user, keywords: 'level detail', run: () => $(`[data-level="${store.get().profile.experience === 'expert' ? 'beginner' : 'expert'}"]`).click() },
  { id: 'portfolio', label: 'Edit portfolio', icon: ICON.pie, keywords: 'holdings settings', run: () => openSettings('portfolio') },
  { id: 'profile', label: 'Edit profile', icon: ICON.user, keywords: 'name settings', run: () => openSettings('profile') },
  { id: 'export', label: 'Export conversation as Markdown', icon: ICON.download, keywords: 'download save', hidden: !(state.chatId && chats.get(state.chatId)?.messages.length), run: exportChat },
  { id: 'sidebar', label: 'Toggle sidebar', icon: ICON.sidebar, keys: 'mod+\\', run: () => setSidebar($('#app').dataset.sidebar !== 'open') },
];
const palette = { items: [], index: 0 };
function renderPalette() {
  const q = $('#palette-input').value;
  palette.items = paletteResults(COMMANDS(), chats.list(), q, 10);
  palette.index = Math.min(palette.index, Math.max(0, palette.items.length - 1));
  const cmds = palette.items.filter(r => r.kind === 'command'), convs = palette.items.filter(r => r.kind === 'chat');
  const row = r => { const i = palette.items.indexOf(r); return `<li class="pal-item" role="option" id="pal-${i}" data-i="${i}" aria-selected="${i === palette.index}">${r.icon ?? ICON.chat}<span>${esc(r.label)}</span>${r.keys ? `<span class="h">${kbdHTML(r.keys)}</span>` : ''}</li>`; };
  $('#palette-list').innerHTML = palette.items.length
    ? `${cmds.length ? `<li class="pal-group" role="presentation">Actions</li>${cmds.map(row).join('')}` : ''}${convs.length ? `<li class="pal-group" role="presentation">Conversations</li>${convs.map(row).join('')}` : ''}`
    : '<li class="pal-empty">No matching command or conversation.</li>';
  $('#palette-input').setAttribute('aria-activedescendant', palette.items.length ? `pal-${palette.index}` : '');
  $(`#pal-${palette.index}`)?.scrollIntoView({ block: 'nearest' });
}
function openPalette() {
  if ($('#palette').open) return;
  document.querySelectorAll('.menu').forEach(m => { m.hidden = true; });
  $('#palette-input').value = ''; palette.index = 0;
  renderPalette();
  $('#palette').showModal();
  $('#palette-input').focus();
}
function runPalette(i) {
  const r = palette.items[i];
  if (!r) return;
  $('#palette').close();
  if (r.kind === 'chat') { openChat(r.chatId); return; }
  r.run();
}
$('#palette-input').addEventListener('input', () => { palette.index = 0; renderPalette(); });
$('#palette-input').addEventListener('keydown', e => {
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); const n = palette.items.length; if (n) { palette.index = (palette.index + (e.key === 'ArrowDown' ? 1 : -1) + n) % n; renderPalette(); } }
  if (e.key === 'Enter') { e.preventDefault(); runPalette(palette.index); }
});
$('#palette-list').addEventListener('click', e => { const it = e.target.closest('[data-i]'); if (it) runPalette(Number(it.dataset.i)); });
$('#palette-list').addEventListener('mousemove', e => { const it = e.target.closest('[data-i]'); if (it && Number(it.dataset.i) !== palette.index) { palette.index = Number(it.dataset.i); renderPalette(); } });
$('#palette').addEventListener('click', e => { if (e.target === $('#palette')) $('#palette').close(); });
$('#palette-btn').addEventListener('click', openPalette);
$('#palette-sb').addEventListener('click', openPalette);

// ---------- keyboard shortcuts ----------
document.querySelectorAll('kbd[data-kbd]').forEach(k => { k.outerHTML = kbdHTML(k.dataset.kbd).replace(/<kbd>/g, '<kbd data-kbd>'); });
document.addEventListener('keydown', e => {
  const mod = MAC ? e.metaKey : e.ctrlKey;
  if (mod && !e.shiftKey && e.key.toLowerCase() === 'k') { e.preventDefault(); $('#palette').open ? $('#palette').close() : openPalette(); return; }
  if (mod && e.shiftKey && e.key.toLowerCase() === 'o') { e.preventDefault(); newChat(); return; }
  if (mod && e.key === '\\') { e.preventDefault(); setSidebar($('#app').dataset.sidebar !== 'open'); return; }
  const typing = e.target.closest?.('input, textarea, select, [contenteditable]');
  if (!typing && !document.querySelector('dialog[open]') && e.key === '/') { e.preventDefault(); input.focus(); }
});

// ---------- My portfolio page ----------
$('#portfolio-view').addEventListener('click', e => {
  const b = e.target.closest('[data-pf]');
  if (!b) return;
  const action = b.dataset.pf;
  if (action === 'edit') openSettings('portfolio');
  if (action === 'profile') openSettings('profile');
  if (action === 'ask') { router.show('agent'); send('What moved my portfolio most in 2021–2026: interest rates, stocks or oil?'); }
  if (action === 'save') {
    const ws = store.get();
    if ((ws.portfolios ?? []).length >= 20) { toast('You can keep up to 20 saved portfolios. Delete one first.'); return; }
    const copy = snapshotPortfolio(ws, `${portfolioName(ws).replace(' · sample', '’s sample')} · ${new Date().toLocaleDateString('en-CA', { month: 'short', day: 'numeric' })}`);
    store.update(next => { next.portfolios = [copy, ...(next.portfolios ?? [])]; });
    syncWorkspace(); renderPortfolio(); toast('Portfolio saved');
  }
  if (action === 'use') {
    store.update(next => { useSaved(next, b.dataset.id); });
    syncWorkspace(); renderProfile(); renderThread(); toast('Portfolio switched');
  }
  if (action === 'delete' && confirm('Delete this saved portfolio?')) {
    store.update(next => { next.portfolios = (next.portfolios ?? []).filter(p => p.id !== b.dataset.id); });
    syncWorkspace(); renderPortfolio(); toast('Saved portfolio deleted');
  }
});

// Hover/focus math explanations for the inline [measured] tags.
attachMeasuredTips($('#thread'), i => (state.chatId ? chats.get(state.chatId)?.messages[i] : null));

// ---------- start ----------
initAgent();
try { storage?.removeItem('cascade.mode'); } catch {}  // the old Agent/Offline preference
setSidebar(!narrow.matches && pref('cascade.sidebar') !== 'closed', false);
state.chatId = null; // open on a fresh chat, like other chat apps
renderAccount();
router.start();
if (auth.configured() && auth.session()) startSession();
else { renderChatList(); renderProfile(); renderThread(); if (auth.configured()) openLogin(); }
// Exploring does not require a profile. Profile and portfolio remain editable in settings.
