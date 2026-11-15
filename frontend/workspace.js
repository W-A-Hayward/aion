import { createWorkspaceStore, PERSONAS, CORE_TICKERS, DEFAULT_NAME, MAX_SAVED, portfolioRows, validateHoldings, splitEvenly, parseImport } from './workspace-store.js';
import { renderWorkspace, initials, tickerOptions } from './workspace-render.js';
import { SHOCKS, TICKER_INFO, ETF_TICKERS, STOCK_TICKERS, isSupported } from './config.js';
import { escapeHTML as esc, hasEstimate, shortTicker } from './formatters.js';
import { loadSnapshot } from './api.js';

export function initWorkspace({ getInvestigation, openInvestigation, setMode }) {
  const $ = selector => document.querySelector(selector);
  let storage; try { storage = window.localStorage; } catch { storage = null; }
  const store = createWorkspaceStore(storage);
  let data = null, tab = 'portfolio', shock = 30, loading = true, toastTimer, loadController;
  let view = location.hash && location.hash !== '#workspace' ? 'research' : 'workspace';
  const host = $('#workspace-content');

  function toast(message) {
    clearTimeout(toastTimer);
    $('#workspace-toast').textContent = message; $('#workspace-toast').hidden = false;
    toastTimer = setTimeout(() => { $('#workspace-toast').hidden = true; }, 5000);
  }
  const persistenceNote = () => store.isPersistent() ? 'Saved in this browser.' : 'Saved for this session only; browser storage is unavailable.';

  function render() {
    const workspace = store.get();
    renderWorkspace(host, { data, workspace, tab, shock, persistent: store.isPersistent(), loading });
    const named = workspace.profile.name !== DEFAULT_NAME;
    $('#profile-open').textContent = initials(workspace.profile.name);
    $('#profile-open').setAttribute('aria-label', named ? `Edit ${workspace.profile.name}’s profile` : 'Set up your profile');
    refreshResearchActions();
  }

  function refreshResearchActions() {
    const current = getInvestigation(), workspace = store.get();
    const row = current.data?.tables.sensitivities.find(item => item.ticker === current.ticker);
    const watched = workspace.watchlist.includes(current.ticker);
    $('#watch-current').textContent = `${watched ? '★ Watching' : '☆ Watch'} ${shortTicker(current.ticker)}`;
    $('#watch-current').setAttribute('aria-pressed', String(watched));
    $('#save-research').disabled = !hasEstimate(row) || current.benchmark !== 'brent';
    $('#research-context').textContent = `${workspace.profile.name === DEFAULT_NAME ? 'Your workspace' : workspace.profile.name} / ${current.source === 'preview' ? 'local preview research' : 'backend research · provenance unverified'}`;
  }

  function changeView(next, scroll = true) {
    view = next;
    $('#workspace-view').hidden = view !== 'workspace';
    $('#research-view').hidden = view !== 'research';
    document.querySelectorAll('[data-view]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.view === view)));
    document.querySelector('.steps-nav')?.toggleAttribute('hidden', view !== 'research');
    if (view === 'workspace') { document.title = 'My workspace — Cascade'; if (location.hash) history.replaceState(null, '', location.pathname + location.search); }
    if (scroll) window.scrollTo({ top: 0, behavior: 'instant' });
  }

  async function loadData() {
    loadController?.abort();
    const controller = new AbortController(); loadController = controller; loading = true; render();
    try {
      const next = await loadSnapshot({ signal: controller.signal });
      for (const key of ['persona_holdings', 'portfolio_beta', 'alternatives']) if (!next[key].length) throw Error('Incomplete snapshot');
      data = next;
    } catch {
      if (controller.signal.aborted) return;
      data = null; toast('The local portfolio snapshot could not load. Your saved workspace is intact.');
    } finally {
      if (!controller.signal.aborted) { loading = false; render(); }
    }
  }

  const closeButtons = dialog => dialog.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => dialog.close()));
  const dialogHead = () => `<div class="dialog-close"><button type="button" class="ghost-button" data-close-dialog aria-label="Close dialog">Close</button></div>`;

  function openProfile() {
    const profile = store.get().profile, dialog = $('#profile-dialog');
    dialog.innerHTML = `${dialogHead('Local profile')}<h2 id="profile-title">Profile</h2>
      <p class="note">There’s no sign-up: no email, no password, nothing sent anywhere. Your profile, portfolios and notes stay in this browser. Use Export to move them to another device. These settings don’t assess investment suitability.</p>
      <form id="profile-form"><label class="form-field">Display name<input name="name" maxlength="60" required value="${esc(profile.name === DEFAULT_NAME ? '' : profile.name)}" placeholder="Your name" autocomplete="nickname"></label>
      <label class="form-field">What are you researching?<input name="goal" maxlength="140" required value="${esc(profile.goal)}"></label>
      <label class="form-field">How should results be explained?<select name="experience"><option value="beginner" ${profile.experience === 'beginner' ? 'selected' : ''}>Plain language</option><option value="expert" ${profile.experience === 'expert' ? 'selected' : ''}>Expert detail</option></select></label>
      <p class="note">Both use the same numbers. All returns are in CAD.</p>
      <div class="dialog-actions"><button type="button" class="ghost-button" data-close-dialog>Cancel</button><button class="primary-button" type="submit">Save profile</button></div></form>`;
    closeButtons(dialog);
    dialog.querySelector('form').addEventListener('submit', event => {
      event.preventDefault();
      const values = new FormData(event.currentTarget), experience = String(values.get('experience'));
      store.update(next => { next.profile = { name: String(values.get('name')), goal: String(values.get('goal')), experience }; });
      setMode(experience); dialog.close(); render(); toast(persistenceNote());
    });
    dialog.showModal();
  }

  function openBuilder({ name = 'My mock portfolio', holdings = [{ ticker: 'XIU.TO', weight: .5 }, { ticker: 'VFV.TO', weight: .5 }], editing = false } = {}) {
    const dialog = $('#portfolio-dialog');
    let draft = structuredClone(holdings);
    dialog.innerHTML = `${dialogHead('Mock portfolio')}<h2 id="portfolio-title">Custom portfolio</h2>
      <p class="note">Pick from the <b>${CORE_TICKERS.length} supported tickers</b>: ${ETF_TICKERS.length} ETFs and ${STOCK_TICKERS.length} stocks with five years of weekly data in the data contract. Other tickers can’t be added because there are no numbers for them. Weights must add up to exactly 100%. This is a hypothetical mix, not an investment account.</p>
      <form id="builder-form" novalidate><label class="form-field">Portfolio name<input id="portfolio-name" name="name" value="${esc(name)}" maxlength="60" required></label>
      <div id="holding-editor" class="holding-editor"></div>
      <div class="builder-tools"><button type="button" class="ghost-button" id="add-holding">+ Add holding</button><button type="button" class="ghost-button" id="split-even">Split evenly</button></div>
      <div id="weight-total" class="editor-total" role="status" aria-live="polite"></div>
      <p class="note">Your mix gets a proxy estimate (sum of weight × beta) and illustrative shock estimates. This is not the portfolio’s measured oil beta. A measured beta and 95% range require a regression on the portfolio’s own returns; custom portfolios are not accepted by the current chat API.</p>
      <p id="builder-error" class="form-error" role="alert"></p>
      <div class="dialog-actions"><button type="button" class="ghost-button" data-close-dialog>Cancel</button><button class="primary-button" type="submit">Save mock portfolio</button></div></form>`;
    const editor = dialog.querySelector('#holding-editor');
    const readDraft = () => [...editor.querySelectorAll('.portfolio-editor-row')].map(row => ({ ticker: row.querySelector('select').value, weight: Number(row.querySelector('input').value) / 100 }));
    function updateTotal() {
      draft = readDraft();
      const total = draft.reduce((sum, row) => sum + (Number.isFinite(row.weight) ? row.weight : 0), 0) * 100;
      const diff = 100 - total, done = Math.abs(diff) < 0.0001;
      const box = dialog.querySelector('#weight-total');
      box.className = `editor-total ${done ? 'ok' : 'off'}`;
      box.textContent = done ? `Total 100% ✓` : `Total ${total.toFixed(2)}% · ${diff > 0 ? `${diff.toFixed(2)}% left to allocate` : `${(-diff).toFixed(2)}% over`}`;
      const used = draft.map(row => row.ticker);
      editor.querySelectorAll('select').forEach(select => select.querySelectorAll('option').forEach(option => { option.disabled = option.value !== select.value && used.includes(option.value); }));
      dialog.querySelector('#add-holding').disabled = draft.length >= CORE_TICKERS.length;
      dialog.querySelector('#builder-error').textContent = '';
    }
    function drawRows() {
      const used = draft.map(row => row.ticker);
      editor.innerHTML = draft.map((row, i) => `<div class="portfolio-editor-row"><label>Holding ${i + 1}<select aria-label="Holding ${i + 1} ticker">${tickerOptions(row.ticker, used)}</select><small class="holding-blurb">${esc(TICKER_INFO[row.ticker]?.blurb || '')}</small></label><label>Weight %<input type="number" inputmode="decimal" min="0.01" max="100" step="0.01" value="${Number((row.weight * 100).toFixed(2))}" required aria-label="Holding ${i + 1} weight percent"></label><button type="button" class="ghost-button" data-remove-holding="${i}" aria-label="Remove holding ${i + 1}" ${draft.length === 1 ? 'disabled' : ''}>×</button></div>`).join('');
      updateTotal();
    }
    editor.addEventListener('input', updateTotal);
    editor.addEventListener('change', event => { if (event.target.matches('select')) { draft = readDraft(); drawRows(); } });
    editor.addEventListener('click', event => {
      const button = event.target.closest('[data-remove-holding]'); if (!button) return;
      draft = readDraft(); draft.splice(Number(button.dataset.removeHolding), 1); drawRows();
      editor.querySelector('select')?.focus();
    });
    dialog.querySelector('#add-holding').addEventListener('click', () => {
      draft = readDraft();
      const ticker = CORE_TICKERS.find(t => !draft.some(row => row.ticker === t)); if (!ticker) return;
      const left = Math.max(0, 1 - draft.reduce((sum, row) => sum + (Number.isFinite(row.weight) ? row.weight : 0), 0));
      draft.push({ ticker, weight: Math.round(left * 10000) / 10000 }); drawRows();
      editor.querySelector('.portfolio-editor-row:last-child select')?.focus();
    });
    dialog.querySelector('#split-even').addEventListener('click', () => {
      draft = readDraft(); const weights = splitEvenly(draft.length);
      draft = draft.map((row, i) => ({ ...row, weight: weights[i] })); drawRows();
    });
    dialog.querySelector('form').addEventListener('submit', event => {
      event.preventDefault(); draft = readDraft();
      const nameValue = dialog.querySelector('#portfolio-name').value.trim();
      const error = !nameValue ? 'Give your portfolio a name.' : validateHoldings(draft);
      if (error) { dialog.querySelector('#builder-error').textContent = error; return; }
      if (store.get().custom && !editing && !confirm('Replace your existing custom mix? Your profile, watchlist and saved research stay.')) return;
      store.update(next => { next.custom = { name: nameValue, holdings: draft }; next.portfolio = 'custom'; });
      tab = 'portfolio'; dialog.close(); render(); toast(`Saved “${nameValue}”. ${persistenceNote()}`);
    });
    drawRows(); closeButtons(dialog); dialog.showModal();
  }

  function openSave(existing) {
    const current = getInvestigation(), row = current.data?.tables.sensitivities.find(item => item.ticker === current.ticker);
    if (!existing && (!hasEstimate(row) || current.benchmark !== 'brent')) { toast('Load a Brent investigation before saving it.'); return; }
    if (!existing && store.get().saved.length >= MAX_SAVED) { toast(`Your notebook is full (${MAX_SAVED} entries). Delete one first.`); return; }
    const ticker = existing?.ticker || current.ticker, source = existing?.source || current.source;
    const dialog = $('#save-dialog');
    dialog.innerHTML = `${dialogHead(existing ? 'Edit note' : 'Save investigation')}<h2 id="save-title">${existing ? 'Edit note' : 'Save investigation'}</h2>
      <p class="note">${esc(ticker)} · ${source === 'api' ? 'backend response, provenance unverified' : 'local preview'}. The beta, range, shock and your note are saved in this browser.</p>
      <form id="save-form"><label class="form-field">Title<input name="title" maxlength="80" required value="${esc(existing?.title || `${shortTicker(ticker)} · oil exposure`)}"></label>
      <label class="form-field">Note<textarea name="note" maxlength="2000" placeholder="What did you learn? What still needs evidence?">${esc(existing?.note || '')}</textarea></label>
      <div class="dialog-actions"><button type="button" class="ghost-button" data-close-dialog>Cancel</button><button type="submit" class="primary-button">${existing ? 'Save note' : 'Save investigation'}</button></div></form>`;
    dialog.querySelector('form').addEventListener('submit', event => {
      event.preventDefault();
      const values = new FormData(event.currentTarget), title = String(values.get('title')).trim(), note = String(values.get('note')).trim();
      store.update(next => {
        if (existing) { const item = next.saved.find(entry => entry.id === existing.id); if (item) { item.title = title; item.note = note; } }
        else next.saved.unshift({ id: crypto.randomUUID(), title, note, ticker: current.ticker, shock: current.shock, source: current.source, mode: current.mode, savedAt: new Date().toISOString(), beta: row.beta_simple, lo: row.lo_simple, hi: row.hi_simple });
      });
      dialog.close(); render(); toast(`${existing ? 'Note updated' : 'Investigation saved'}. ${persistenceNote()}`);
    });
    closeButtons(dialog); dialog.showModal();
  }

  function toggleWatch(ticker) {
    if (!isSupported(ticker)) return;
    const wasWatched = store.get().watchlist.includes(ticker);
    store.update(next => { next.watchlist = wasWatched ? next.watchlist.filter(t => t !== ticker) : [...next.watchlist, ticker]; });
    render(); toast(`${shortTicker(ticker)} ${wasWatched ? 'removed from' : 'added to'} your watchlist. ${persistenceNote()}`);
  }

  function importWorkspace() {
    const input = document.createElement('input');
    input.type = 'file'; input.accept = 'application/json,.json';
    input.addEventListener('change', async () => {
      const file = input.files?.[0]; if (!file) return;
      if (file.size > 1_000_000) { toast('That file is too large to be a Cascade export.'); return; }
      const result = parseImport(await file.text());
      if (result.error) { toast(result.error); return; }
      if (!confirm(`Replace this browser’s workspace with “${result.workspace.profile.name}” from ${file.name}? Export first if you want to keep the current one.`)) return;
      store.replace(result.workspace); tab = 'portfolio'; setMode(result.workspace.profile.experience); render();
      toast(`Workspace imported.${result.dropped ? ' Entries for unsupported tickers were skipped.' : ''} ${persistenceNote()}`);
    });
    input.click();
  }

  function openResearch(settings = {}) { changeView('research'); openInvestigation(settings); }
  const actions = {
    profile: openProfile, build: () => openBuilder(), research: () => openResearch({ ticker: 'XIU.TO', source: 'preview' }),
    'retry-data': loadData, import: importWorkspace,
    'edit-portfolio': () => {
      if (!data) return; const w = store.get();
      openBuilder({ name: w.portfolio === 'custom' ? w.custom.name : `My ${PERSONAS[w.portfolio].name} mix`, holdings: portfolioRows(data, w).map(({ ticker, weight }) => ({ ticker, weight })), editing: w.portfolio === 'custom' });
    },
    export: () => {
      const blob = new Blob([JSON.stringify(store.get(), null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob), a = document.createElement('a');
      a.href = url; a.download = `cascade-workspace-${new Date().toISOString().slice(0, 10)}.json`; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast('Exported your profile, portfolio, watchlist and notes. Use Import to restore them anywhere.');
    },
    reset: () => {
      if (!confirm('Reset your profile, custom mix, watchlist and saved research? This can’t be undone. Export first to keep a copy.')) return;
      store.reset(); tab = 'portfolio'; shock = 30; setMode('beginner'); render(); toast('Workspace reset.');
    },
  };

  host.addEventListener('click', event => {
    const button = event.target.closest('button'); if (!button) return;
    const d = button.dataset;
    if (d.action) { actions[d.action]?.(); return; }
    if (d.workspaceTab) { tab = d.workspaceTab; render(); host.querySelector(`[data-workspace-tab="${tab}"]`)?.focus({ preventScroll: true }); return; }
    if (d.persona) { store.update(next => { next.portfolio = d.persona; }); render(); return; }
    if (d.portfolioShock) { const value = Number(d.portfolioShock); if (SHOCKS.includes(value)) { shock = value; render(); host.querySelector(`[data-portfolio-shock="${value}"]`)?.focus({ preventScroll: true }); } return; }
    if (d.openTicker) { openResearch({ ticker: d.openTicker, source: 'preview' }); return; }
    if (d.unwatch) { toggleWatch(d.unwatch); return; }
    const id = d.openSaved || d.editNote || d.deleteSaved;
    if (id) {
      const entry = store.get().saved.find(item => item.id === id); if (!entry) return;
      if (d.openSaved) openResearch(entry);
      if (d.editNote) openSave(entry);
      if (d.deleteSaved && confirm(`Delete “${entry.title}” from your notebook?`)) { store.update(next => { next.saved = next.saved.filter(item => item.id !== id); }); render(); toast('Entry deleted.'); }
      return;
    }
    if (d.alternative && data) {
      // Same swap as compute/stats.py ALTERNATIVES: amira moves 0.25, others move the whole holding.
      const w = store.get(), holdings = portfolioRows(data, w).map(row => ({ ticker: row.ticker, weight: row.weight }));
      const original = holdings.find(row => row.ticker === d.alternative); if (!original) return;
      const moved = w.portfolio === 'amira' ? .25 : original.weight; original.weight -= moved;
      const replacement = holdings.find(row => row.ticker === d.replacement);
      if (replacement) replacement.weight += moved; else holdings.push({ ticker: d.replacement, weight: moved });
      openBuilder({ name: `${PERSONAS[w.portfolio].name} · ${shortTicker(d.alternative)} → ${shortTicker(d.replacement)}`, holdings: holdings.filter(row => row.weight > 1e-9).map(row => ({ ...row, weight: Math.round(row.weight * 10000) / 10000 })) });
    }
  });
  // Arrow keys move between workspace tabs (WAI-ARIA tabs pattern).
  host.addEventListener('keydown', event => {
    const current = event.target.closest('[data-workspace-tab]'); if (!current || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const tabs = [...host.querySelectorAll('[data-workspace-tab]')], i = tabs.indexOf(current);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (i + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    event.preventDefault(); tabs[next].click();
  });
  host.addEventListener('submit', event => {
    if (event.target.id === 'capital-form') {
      event.preventDefault(); const capital = Number(new FormData(event.target).get('capital'));
      if (Number.isFinite(capital) && capital > 0 && capital <= 100000000) { store.update(next => { next.capital = capital; }); render(); toast('Illustrative capital updated. No money moved.'); }
      else toast('Enter an amount between $1 and $100,000,000.');
    }
    if (event.target.id === 'watch-add-form') {
      event.preventDefault(); const ticker = String(new FormData(event.target).get('ticker'));
      if (store.get().watchlist.includes(ticker)) { toast(`${shortTicker(ticker)} is already on your watchlist.`); return; }
      toggleWatch(ticker);
    }
  });
  document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => {
    changeView(button.dataset.view);
    if (view === 'workspace') render();
  }));
  $('#profile-open').addEventListener('click', openProfile);
  $('#watch-current').addEventListener('click', () => toggleWatch(getInvestigation().ticker));
  $('#save-research').addEventListener('click', () => openSave());
  setMode(store.get().profile.experience); changeView(view, false); loadData();
  return { refreshResearchActions, saveExperience: mode => { store.update(next => { next.profile.experience = mode; }); render(); }, isHome: () => view === 'workspace' };
}
