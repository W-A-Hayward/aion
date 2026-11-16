// A signed-in user's profile, portfolio and conversations, stored by lambdas/userdata (routes /me, /me/chats/{id}).
// The browser keeps a per-user cache (scopedStorage) so the app works instantly; changes are saved to the account
// shortly after they happen and retried if a save fails. Conversations are fetched in full only when opened.
import { config } from './config.js';

export const MAX_CHAT_BYTES = 340_000;   // lambdas/userdata accepts 350 KB per conversation

/** localStorage with every key prefixed by the user, so two accounts on one browser never mix. */
export function scopedStorage(storage, prefix) {
  const k = key => `${prefix}:${key}`;
  return {
    getItem: key => storage?.getItem(k(key)) ?? null,
    setItem: (key, value) => storage?.setItem(k(key), value),
    removeItem: key => storage?.removeItem(k(key)),
    clearAll() {
      try {
        const keys = typeof storage?.key === 'function' ? Array.from({ length: storage.length }, (_, i) => storage.key(i)) : Object.keys(storage ?? {});
        for (const key of keys) if (key?.startsWith(`${prefix}:`)) storage.removeItem(key);
      } catch {}
    },
  };
}

/** Make a conversation fit the per-item limit: older messages lose their bulky metadata first, then drop. */
export function fitConversation(chat, limit = MAX_CHAT_BYTES) {
  const size = c => new TextEncoder().encode(JSON.stringify({ conversation: c })).length;
  let out = structuredClone(chat);
  for (let i = 0; size(out) > limit && i < out.messages.length; i++) {
    const m = out.messages[i];
    for (const key of ['data', 'toolCalls', 'trace', 'progress']) delete m[key];
  }
  while (size(out) > limit && out.messages.length > 2) out.messages.shift();
  return out;
}

export function createUserDataClient(getToken, settings = config, transport = globalThis.fetch) {
  const base = String(settings.userDataUrl ?? '').replace(/\/+$/, '');
  const request = async (method, path, body) => {
    const token = await getToken();
    const response = await transport(`${base}${path}`, { method, credentials: 'omit', cache: 'no-store',
      headers: { Accept: 'application/json', Authorization: `Bearer ${token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}) });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) { const e = Error(data.error || `Request failed (HTTP ${response.status})`); e.status = response.status; throw e; }
    return data;
  };
  return {
    me: () => request('GET', '/me'),
    saveWorkspace: workspace => request('PUT', '/me', { workspace }),
    chat: id => request('GET', `/me/chats/${encodeURIComponent(id)}`),
    saveChat: chat => request('PUT', `/me/chats/${encodeURIComponent(chat.id)}`, { conversation: fitConversation(chat) }),
    deleteChat: id => request('DELETE', `/me/chats/${encodeURIComponent(id)}`),
    deleteAccount: () => request('DELETE', '/me'),
  };
}

/**
 * Debounced, retried saving. `status` reports 'saving' | 'saved' | 'error' for the UI.
 * schedule('workspace') or schedule('chat:<id>') / schedule('delete:<id>').
 */
export function createSyncQueue({ client, getWorkspace, getChat, onStatus = () => {}, delay = 600, retryMs = 15_000, timers = globalThis }) {
  const dirty = new Set();
  let timer = null, running = false;
  const flush = async () => {
    timer = null;
    if (running) { timer = timers.setTimeout(flush, delay); return; }
    running = true;
    onStatus('saving');
    const jobs = [...dirty];
    dirty.clear();
    let failed = false;
    for (const job of jobs) {
      try {
        if (job === 'workspace') await client.saveWorkspace(getWorkspace());
        else if (job.startsWith('chat:')) { const chat = getChat(job.slice(5)); if (chat?.messages?.length) await client.saveChat(chat); }
        else if (job.startsWith('delete:')) await client.deleteChat(job.slice(7));
      } catch (error) {
        if (error.status === 400 || error.status === 413) continue;   // will not succeed on retry
        failed = true; dirty.add(job);
      }
    }
    running = false;
    onStatus(failed ? 'error' : dirty.size ? 'saving' : 'saved');
    if (failed) timer = timers.setTimeout(flush, retryMs);
    else if (dirty.size) timer = timers.setTimeout(flush, delay);
  };
  return {
    schedule(job) {
      if (job.startsWith('delete:')) dirty.delete(`chat:${job.slice(7)}`);
      dirty.add(job);
      onStatus('saving');   // shown straight away, so the user never sees "saved" while a change is pending
      if (timer) timers.clearTimeout(timer);
      timer = timers.setTimeout(flush, delay);
    },
    flush: () => { if (timer) timers.clearTimeout(timer); return flush(); },
    pending: () => dirty.size > 0 || running,
  };
}
