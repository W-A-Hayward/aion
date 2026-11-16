import test from 'node:test';
import assert from 'node:assert/strict';
import { createAuth, checkCredentials, jwtClaims, authConfigured, SESSION_KEY } from './auth.js';
import { createUserDataClient, createSyncQueue, scopedStorage, fitConversation, MAX_CHAT_BYTES } from './cloud-sync.js';
import { createChatStore } from './chat-store.js';

const settings = { auth: { region: 'us-east-1', userPoolId: 'us-east-1_pool', clientId: 'client123' }, userDataUrl: 'https://api.test/' };
const memory = () => { const m = new Map(); return { m, getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k), key: i => [...m.keys()][i] ?? null, get length() { return m.size; } }; };
const b64 = o => Buffer.from(JSON.stringify(o)).toString('base64url');
const idToken = (sub, username, exp = 9e9) => `h.${b64({ sub, 'cognito:username': username, exp })}.s`;
const json = (d, status = 200) => ({ ok: status < 400, status, json: async () => d });

/** A minimal Cognito: users by name, tokens, the actions RIPPLE calls. */
function fakeCognito() {
  const users = new Map(), calls = [];
  let n = 0;
  const transport = async (url, o) => {
    assert.equal(url, 'https://cognito-idp.us-east-1.amazonaws.com/');
    assert.equal(o.headers['Content-Type'], 'application/x-amz-json-1.1');
    const action = o.headers['X-Amz-Target'].split('.').pop(), body = JSON.parse(o.body);
    calls.push({ action, body });
    assert.equal(body.ClientId ?? 'client123', 'client123');
    const err = (type, message = '') => json({ __type: `com.amazonaws#${type}`, message }, 400);
    const tokens = username => ({ AuthenticationResult: { IdToken: idToken(users.get(username).sub, username), AccessToken: `access-${username}-${++n}`, RefreshToken: `refresh-${username}`, ExpiresIn: 3600 } });
    if (action === 'SignUp') {
      if (users.has(body.Username)) return err('UsernameExistsException');
      if (body.Password.length < 8) return err('InvalidPasswordException', 'Password did not conform with policy');
      users.set(body.Username, { password: body.Password, sub: `sub-${body.Username}` });
      return json({ UserConfirmed: true });
    }
    if (action === 'InitiateAuth' && body.AuthFlow === 'USER_PASSWORD_AUTH') {
      const u = users.get(body.AuthParameters.USERNAME);
      return u && u.password === body.AuthParameters.PASSWORD ? json(tokens(body.AuthParameters.USERNAME)) : err('NotAuthorizedException');
    }
    if (action === 'InitiateAuth' && body.AuthFlow === 'REFRESH_TOKEN_AUTH') {
      const name = body.AuthParameters.REFRESH_TOKEN.replace('refresh-', '');
      if (!users.has(name)) return err('NotAuthorizedException');
      const t = tokens(name); delete t.AuthenticationResult.RefreshToken; return json(t);
    }
    if (action === 'ChangePassword') {
      const name = body.AccessToken.split('-')[1];
      if (users.get(name).password !== body.PreviousPassword) return err('NotAuthorizedException');
      users.get(name).password = body.ProposedPassword; return json({});
    }
    if (action === 'RevokeToken') return json({});
    if (action === 'DeleteUser') { users.delete(body.AccessToken.split('-')[1]); return json({}); }
    return err('UnknownAction');
  };
  return { users, calls, transport };
}

test('auth is configured only with a user pool, client and user-data API', () => {
  assert.equal(authConfigured(settings), true);
  assert.equal(authConfigured({ ...settings, userDataUrl: null }), false);
  assert.equal(authConfigured({ auth: { region: 'us-east-1', userPoolId: null, clientId: null }, userDataUrl: null }), false);
});

test('few restrictions: 3–32 character usernames, passwords of 8+ characters', () => {
  assert.equal(checkCredentials('robin', 'password'), null);
  assert.equal(checkCredentials('a.b-c_9', '12345678'), null);
  assert.match(checkCredentials('ro', 'password'), /3–32/);
  assert.match(checkCredentials('has space', 'password'), /letters/);
  assert.match(checkCredentials('robin', 'short'), /8 characters/);
});

test('sign up, stay signed in across reloads, refresh, change password, sign out', async () => {
  const cognito = fakeCognito(), storage = memory();
  let now = 1_000_000;
  const a = createAuth(settings, cognito.transport, storage, () => now);
  assert.equal(a.session(), null);
  const s = await a.signUp('robin', 'correct horse');
  assert.deepEqual(s, { username: 'robin', sub: 'sub-robin' });
  assert.deepEqual(cognito.calls.map(c => c.action), ['SignUp', 'InitiateAuth']);
  assert.equal(cognito.calls[1].body.AuthFlow, 'USER_PASSWORD_AUTH');

  const again = createAuth(settings, cognito.transport, storage, () => now);   // a reload
  assert.deepEqual(again.session(), { username: 'robin', sub: 'sub-robin' });
  const first = await again.idToken();
  assert.equal(jwtClaims(first).sub, 'sub-robin');
  now += 3_600_000;   // the ID token expired: it is refreshed once, even for parallel callers
  const [t1, t2] = await Promise.all([again.idToken(), again.idToken()]);
  assert.equal(t1, t2);
  assert.equal(cognito.calls.filter(c => c.body.AuthFlow === 'REFRESH_TOKEN_AUTH').length, 1);
  assert.ok(JSON.parse(storage.getItem(SESSION_KEY)).refreshToken, 'the refresh token is kept after a refresh');

  await assert.rejects(again.changePassword('wrong', 'new password 1'), e => e.code === 'NotAuthorizedException');
  await again.changePassword('correct horse', 'new password 1');
  await again.signOut();
  assert.equal(again.session(), null);
  assert.equal(storage.getItem(SESSION_KEY), null);
  assert.equal(cognito.calls.at(-1).action, 'RevokeToken');
  await assert.rejects(a.signIn('robin', 'correct horse'), /Wrong username or password/);
  assert.deepEqual(await a.signIn('robin', 'new password 1'), { username: 'robin', sub: 'sub-robin' });
});

test('sign-in errors are plain sentences; invalid input never reaches Cognito', async () => {
  const cognito = fakeCognito();
  const a = createAuth(settings, cognito.transport, memory());
  await a.signUp('robin', 'password1');
  await assert.rejects(a.signUp('robin', 'password2'), /username is taken/);
  await assert.rejects(a.signIn('nobody', 'password1'), /Wrong username or password/);
  const before = cognito.calls.length;
  await assert.rejects(a.signIn('x', 'password1'), /3–32/);
  await assert.rejects(a.signUp('valid', 'short'), /8 characters/);
  assert.equal(cognito.calls.length, before);
  const down = createAuth(settings, async () => { throw new TypeError('Failed to fetch'); }, memory());
  await assert.rejects(down.signIn('robin', 'password1'), /Couldn’t reach the sign-in service/);
  const lambda = createAuth(settings, async () => json({ __type: 'UserLambdaValidationException', message: 'PreSignUp failed with error Usernames are 3-32 characters.' }, 400), memory());
  await assert.rejects(lambda.signUp('robin', 'password1'), /^Error: Usernames are 3-32 characters\.$|Usernames are 3-32 characters\./);
});

test('an expired refresh token signs the user out cleanly', async () => {
  const cognito = fakeCognito(), storage = memory();
  let now = 0;
  const a = createAuth(settings, cognito.transport, storage, () => now);
  await a.signUp('robin', 'password1');
  cognito.users.delete('robin');
  now += 4e6;
  await assert.rejects(a.idToken(), e => e.code === 'SignedOut');
  assert.equal(a.session(), null);
});

test('user-data client sends the ID token and maps every route', async () => {
  const seen = [];
  const client = createUserDataClient(async () => 'TOKEN', settings, async (url, o) => {
    seen.push([o.method, url, o.headers.Authorization, o.body && JSON.parse(o.body)]);
    return json(url.endsWith('/me') && o.method === 'GET' ? { username: 'robin', workspace: null, chats: [] } : { ok: true });
  });
  await client.me();
  await client.saveWorkspace({ portfolio: 'robert' });
  await client.chat('c 1');
  await client.saveChat({ id: 'c1', title: 'Q', messages: [{ role: 'user', text: 'hi' }] });
  await client.deleteChat('c1');
  await client.deleteAccount();
  assert.deepEqual(seen.map(([m, u]) => `${m} ${u}`), ['GET https://api.test/me', 'PUT https://api.test/me', 'GET https://api.test/me/chats/c%201',
    'PUT https://api.test/me/chats/c1', 'DELETE https://api.test/me/chats/c1', 'DELETE https://api.test/me']);
  assert.ok(seen.every(s => s[2] === 'Bearer TOKEN'));
  assert.deepEqual(seen[1][3], { workspace: { portfolio: 'robert' } });
  assert.equal(seen[3][3].conversation.messages[0].text, 'hi');
  const failing = createUserDataClient(async () => 'T', settings, async () => json({ error: 'conversation not found' }, 404));
  await assert.rejects(failing.chat('x'), e => e.status === 404 && /not found/.test(e.message));
});

test('large conversations shrink to fit: bulky metadata first, then the oldest messages', () => {
  const big = { id: 'c1', title: 'Q', messages: Array.from({ length: 40 }, (_, i) => ({ role: 'assistant', text: `answer ${i}`, data: { blob: 'x'.repeat(20_000) } })) };
  const fit = fitConversation(big);
  assert.ok(JSON.stringify({ conversation: fit }).length <= MAX_CHAT_BYTES);
  assert.equal(fit.messages.length, 40, 'only metadata was dropped');
  assert.ok(fit.messages.at(-1).data, 'the newest answers keep their data');
  const huge = { id: 'c2', messages: Array.from({ length: 40 }, (_, i) => ({ role: 'user', text: 'y'.repeat(20_000) + i })) };
  assert.ok(fitConversation(huge).messages.length < 40);
  assert.equal(big.messages[0].data.blob.length, 20_000, 'the original is not modified');
});

test('save queue batches changes, retries failures and reports status', async () => {
  const timers = { queue: [], setTimeout(fn) { this.queue.push(fn); return this.queue.length; }, clearTimeout() {} };
  const saved = [], statuses = [];
  let fail = 1;
  const client = {
    saveWorkspace: async ws => { if (fail-- > 0) { const e = Error('down'); e.status = 503; throw e; } saved.push(['ws', ws.v]); },
    saveChat: async c => saved.push(['chat', c.id]), deleteChat: async id => saved.push(['del', id]),
  };
  const q = createSyncQueue({ client, getWorkspace: () => ({ v: 2 }), getChat: id => ({ id, messages: [{}] }), onStatus: s => statuses.push(s), timers });
  q.schedule('workspace'); q.schedule('chat:a'); q.schedule('chat:a'); q.schedule('chat:b'); q.schedule('delete:b');
  await q.flush();
  assert.deepEqual(saved, [['chat', 'a'], ['del', 'b']], 'duplicates merged; a deleted chat is not saved first');
  assert.equal(statuses.at(-1), 'error');
  assert.ok(q.pending(), 'the failed save is kept for retry');
  await q.flush();
  assert.deepEqual(saved.at(-1), ['ws', 2]);
  assert.equal(statuses.at(-1), 'saved');
});

test('per-user storage keeps accounts apart; the chat store merges the account’s list', () => {
  const raw = memory();
  const a = scopedStorage(raw, 'ripple.user.sub-a'), b = scopedStorage(raw, 'ripple.user.sub-b');
  const ca = createChatStore(a);
  const local = ca.create();
  ca.add(local.id, { role: 'user', text: 'only on this device' });
  assert.equal(createChatStore(b).list().length, 0, 'user B does not see user A’s cache');
  const toUpload = ca.merge([{ id: 'server-1', title: 'From my laptop', updatedAt: '2099-01-01T00:00:00Z' }]);
  assert.deepEqual(toUpload, [local.id], 'local conversations the account lacks are uploaded');
  assert.equal(ca.list()[0].id, 'server-1');
  assert.equal(ca.get('server-1').remote, true);
  ca.replace({ id: 'server-1', title: 'From my laptop', updatedAt: '2099-01-01T00:00:00Z', messages: [{ role: 'user', text: 'hi' }] });
  assert.equal(ca.get('server-1').remote, undefined);
  assert.equal(ca.get('server-1').messages.length, 1);
  a.clearAll();
  assert.equal([...raw.m.keys()].filter(k => k.startsWith('ripple.user.sub-a')).length, 0);
});
