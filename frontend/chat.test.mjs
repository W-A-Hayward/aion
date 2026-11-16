import test from 'node:test';
import assert from 'node:assert/strict';
import { createChatStore, getAccount, createAccount, deleteAccount } from './chat-store.js';

const memory = () => { const m = new Map(); return { getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k) }; };

test('chat store keeps conversations, titles them and survives reload', () => {
  const s = memory();
  const a = createChatStore(s);
  const c = a.create();
  a.add(c.id, { role: 'user', text: 'First question about XIU' });
  a.add(c.id, { role: 'assistant', kind: 'local', text: 'ok' });
  const b = createChatStore(s);
  assert.equal(b.list()[0].title, 'First question about XIU');
  assert.equal(b.get(c.id).messages.length, 2);
  b.remove(c.id);
  assert.equal(createChatStore(s).list().length, 0);
});

test('account exists only after sign-up and is erased on sign-out', () => {
  const s = memory();
  assert.equal(getAccount(s), null);
  createAccount(s);
  assert.ok(getAccount(s));
  deleteAccount(s);
  assert.equal(getAccount(s), null);
});
