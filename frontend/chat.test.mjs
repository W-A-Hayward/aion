import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { normalizeTables } from './api.js';
import { answerLocally, findTickers, findShock, searchPassages } from './chat-answer.js';
import { createChatStore, getAccount, createAccount, deleteAccount } from './chat-store.js';

const tables = normalizeTables(JSON.parse(await readFile(new URL('./preview-data.json', import.meta.url))));
const evidence = JSON.parse(await readFile(new URL('./evidence-preview.json', import.meta.url)));
const custom = { profile: { name: 'Test', experience: 'beginner' }, portfolio: 'custom', capital: 10000,
  custom: { name: 'Mine', holdings: [{ ticker: 'XIU.TO', weight: 0.6 }, { ticker: 'ENB.TO', weight: 0.4 }] } };
const memory = () => { const m = new Map(); return { getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k) }; };

test('tickers are recognised by symbol and company name', () => {
  assert.deepEqual(findTickers('How reliable is XIU?'), ['XIU.TO']);
  assert.deepEqual(findTickers('Enbridge versus Exxon').sort(), ['ENB.TO', 'XOM']);
  assert.deepEqual(findTickers('what about my money'), []);
});

test('shock direction follows the wording', () => {
  assert.equal(findShock('if Brent drops 30%'), -30);
  assert.equal(findShock('oil up 15%'), 15);
  assert.equal(findShock('-15% oil'), -15);
  assert.equal(findShock('no shock here'), null);
});

test('portfolio answer uses the profile holdings and the saved betas', () => {
  const r = answerLocally('What happens to my portfolio if Brent drops 30%?', { tables, workspace: custom, evidence });
  const beta = 0.6 * tables.sensitivities.find(s => s.ticker === 'XIU.TO').beta_simple + 0.4 * tables.sensitivities.find(s => s.ticker === 'ENB.TO').beta_simple;
  const impact = 100 * Math.expm1(beta * Math.log1p(-0.3));
  assert.match(r.text, /Mine/);
  assert.match(r.text, new RegExp(`${impact.toFixed(2).replace('-', '-')}%`));
  assert.equal(r.table.rows.length, 2);
  assert.ok(r.steps.length >= 2);
});

test('unsupported shock sizes are not computed silently', () => {
  const r = answerLocally('what if oil rises 20%', { tables, workspace: custom, evidence });
  assert.match(r.text, /Only ±15% and ±30%/);
});

test('document answers quote real passages and never claim a share-price direction', () => {
  const r = answerLocally('What do the companies say about diesel?', { tables, workspace: custom, evidence });
  assert.ok(r.quotes.length > 0);
  for (const q of r.quotes) assert.ok(evidence.passages.some(p => p.excerpt_original === q.text));
  assert.match(r.text, /don’t say which way the shares move/);
  assert.ok(searchPassages(evidence.passages, 'zzzz nothing').length === 0);
});

test('small talk gets help, not an invented analysis', () => {
  const r = answerLocally('hello', { tables, workspace: custom, evidence });
  assert.equal(r.table, null);
  assert.match(r.text, /I can answer from the saved data/);
});

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
