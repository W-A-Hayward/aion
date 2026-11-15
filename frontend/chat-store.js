// Conversations and sign-up state, kept in this browser (localStorage). There is no account server yet:
// "signing up" creates a local profile; signing out erases it from this browser.
export const CHATS_KEY = 'cascade.chats.v1';
export const ACCOUNT_KEY = 'cascade.account.v1';
const MAX_CHATS = 50, MAX_MESSAGES = 60;

const read = (storage, key, fallback) => {
  try { const raw = storage?.getItem(key); return raw ? JSON.parse(raw) : fallback; } catch { return fallback; }
};
const write = (storage, key, value) => { try { storage?.setItem(key, JSON.stringify(value)); return true; } catch { return false; } };
const newId = () => (crypto.randomUUID?.() ?? `c-${Date.now()}-${Math.random().toString(16).slice(2)}`);

export function createChatStore(storage = globalThis.localStorage) {
  let chats = read(storage, CHATS_KEY, []);
  if (!Array.isArray(chats)) chats = [];
  chats = chats.filter(c => c && typeof c.id === 'string' && Array.isArray(c.messages));
  const save = () => write(storage, CHATS_KEY, chats);
  return {
    list: () => chats.map(({ id, title, updatedAt }) => ({ id, title, updatedAt })),
    get: id => chats.find(c => c.id === id) ?? null,
    create() {
      const chat = { id: newId(), title: 'New chat', createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), sessionId: null, messages: [] };
      chats.unshift(chat);
      chats = chats.slice(0, MAX_CHATS);
      save();
      return chat;
    },
    add(id, message) {
      const chat = chats.find(c => c.id === id);
      if (!chat) return null;
      chat.messages.push(message);
      chat.messages = chat.messages.slice(-MAX_MESSAGES);
      if (chat.title === 'New chat' && message.role === 'user') chat.title = message.text.slice(0, 60);
      chat.updatedAt = new Date().toISOString();
      chats = [chat, ...chats.filter(c => c !== chat)];
      save();
      return chat;
    },
    setSession(id, sessionId) { const chat = chats.find(c => c.id === id); if (chat) { chat.sessionId = sessionId; save(); } },
    remove(id) { chats = chats.filter(c => c.id !== id); save(); },
    clear() { chats = []; try { storage?.removeItem(CHATS_KEY); } catch {} },
  };
}

export const getAccount = (storage = globalThis.localStorage) => {
  const a = read(storage, ACCOUNT_KEY, null);
  return a && typeof a.createdAt === 'string' ? a : null;
};
export const createAccount = (storage = globalThis.localStorage) => {
  const a = { createdAt: new Date().toISOString() };
  write(storage, ACCOUNT_KEY, a);
  return a;
};
export const deleteAccount = (storage = globalThis.localStorage) => { try { storage?.removeItem(ACCOUNT_KEY); } catch {} };
