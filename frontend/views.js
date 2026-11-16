// One shell, several views: the agent (landing), statistics, sources, about and the account's portfolio page.
// The URL carries the view (?view=sources) so links, reloads and the back button work. Heavy views load their
// modules the first time they are opened, so the agent stays fast.
export const VIEWS = Object.freeze(['agent', 'statistics', 'sources', 'about', 'portfolio']);
const TITLES = { agent: 'RIPPLE Agent', statistics: 'Statistics', sources: 'Sources', about: 'About', portfolio: 'My portfolio' };

let library = null;
/** Load the source library once (it fetches the catalog on start). */
export function ensureLibrary() {
  library ??= import('./library.js');
  return library;
}

/** Open a source in the library: switches to Sources, then selects it (detail: {sourceId?, hash?, page?, ticker?}). */
export async function openSource(router, detail = {}) {
  router.show('sources');
  await ensureLibrary();
  document.dispatchEvent(new CustomEvent('ripple:open-library', { detail }));
}

export function createRouter({ onShow = () => {}, doc = document, win = window } = {}) {
  let current = null;
  const fromUrl = () => new URLSearchParams(win.location.search).get('view') || 'agent';
  const show = (name, { push = true } = {}) => {
    if (!VIEWS.includes(name)) name = 'agent';
    for (const v of doc.querySelectorAll('.view[data-view]')) v.hidden = v.dataset.view !== name;   // not <body data-view>
    for (const b of doc.querySelectorAll('.app-nav [data-go]')) {
      if (b.dataset.go === name) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
    }
    doc.body.dataset.view = name;
    const title = doc.querySelector('#view-title');
    if (title) title.textContent = TITLES[name];
    doc.title = name === 'agent' ? 'RIPPLE AI' : `${TITLES[name]} · RIPPLE AI`;
    if (push && name !== current) {
      const url = new URL(win.location.href);
      if (name === 'agent') url.searchParams.delete('view'); else url.searchParams.set('view', name);
      win.history.pushState({ view: name }, '', url);
    }
    const previous = current;
    current = name;
    if (name === 'sources') ensureLibrary();
    onShow(name, previous);
  };
  doc.addEventListener('click', event => {
    const go = event.target.closest('[data-go]');
    if (go) { event.preventDefault(); show(go.dataset.go); }
  });
  win.addEventListener('popstate', () => show(fromUrl(), { push: false }));
  return { show, current: () => current, start: () => show(fromUrl(), { push: false }) };
}
