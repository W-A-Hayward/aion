// Dependency-free smoke checks with an installed Chrome. Temporary profile, loopback server only.
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { readFile, mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, extname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const root = fileURLToPath(new URL('./', import.meta.url));
const expectedCatalog = JSON.parse(await readFile(new URL('./library-catalog.json', import.meta.url), 'utf8'));
const dir = await mkdtemp(join(tmpdir(), 'ripple-evidence-ui-'));
const profile = join(dir, 'chrome-profile');
const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml' };
const server = createServer(async (req, res) => {
  try {
    const p = resolve(root, '.' + new URL(req.url, 'http://localhost').pathname.replace(/\/$/, '/index.html'));
    if (!p.startsWith(root)) throw new Error('outside frontend');
    res.setHeader('Content-Type', mime[extname(p)] || 'application/octet-stream');
    res.end(await readFile(p));
  } catch { res.statusCode = 404; res.end('Not found'); }
});
await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
const origin = `http://127.0.0.1:${server.address().port}`;
const chrome = spawn(process.env.RIPPLE_CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', [
  '--headless', '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--no-first-run',
  '--no-default-browser-check', '--disable-background-networking', '--disable-component-update',
  '--disable-sync', '--disable-default-apps', '--metrics-recording-only',
  '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost', 'about:blank',
], { stdio: ['ignore', 'ignore', 'pipe'] });
let ws;
const sleep = ms => new Promise(r => setTimeout(r, ms));
// Statistics come only from the backend (GET /research). The check answers that one URL from this fixture.
const RESEARCH_URL = 'https://wm28zdv834.execute-api.us-east-1.amazonaws.com/research';
let failResearch = false;
const researchFixture = ticker => ({
  sensitivities: [
    { ticker: 'XIU.TO', beta_simple: 0.011, lo_simple: -0.032, hi_simple: 0.054, p_simple: 0.6, n_weeks: 261 },
    { ticker: 'XOM', beta_simple: 0.357, lo_simple: 0.3, hi_simple: 0.41, p_simple: 0.0001, n_weeks: 261 },
    { ticker: 'TLT', beta_simple: -0.089, lo_simple: -0.126, hi_simple: -0.053, p_simple: 0.001, n_weeks: 261 },
  ],
  scenarios: [{ subject: ticker, subject_type: 'ticker', shock_pct: 30, impact_pct: 0.28, lo_pct: -0.8, hi_pct: 1.4 }],
  rolling: [{ ticker, week: '2025-01-03', beta_52w: 0.05 }, { ticker, week: '2026-11-13', beta_52w: -0.01 }],
  confidence: [], chain_reconciliation: [], evidence: [], meta: { ticker, as_of: '2026-11-13', missing: [] },
});
try {
  const endpoint = await new Promise((resolve, reject) => {
    let stderr = '';
    const timer = setTimeout(() => reject(new Error('Chrome did not start in 15 seconds')), 15000);
    chrome.on('error', error => { clearTimeout(timer); reject(error); });
    chrome.on('exit', code => { clearTimeout(timer); reject(new Error(`Chrome exited ${code}`)); });
    chrome.stderr.on('data', bytes => {
      stderr += bytes.toString();
      const match = stderr.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (match) { clearTimeout(timer); resolve(match[1]); }
    });
  });
  ws = new WebSocket(endpoint);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  let sequence = 0, session, failFixture = false, failCatalog = false;
  const pending = new Map(), errors = [], externalRequests = [];
  function send(method, params = {}, sessionId = session) {
    const id = ++sequence;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pending.delete(id); reject(new Error(`Timed out: ${method}`)); }, 10000);
      pending.set(id, { resolve: result => { clearTimeout(timer); resolve(result); }, reject });
      ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    });
  }
  ws.onmessage = event => {
    const m = JSON.parse(event.data);
    if (m.id) {
      const p = pending.get(m.id); pending.delete(m.id);
      if (m.error) p?.reject(new Error(m.error.message)); else p?.resolve(m.result);
    }
    if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.text + ': ' + (m.params.exceptionDetails.exception?.description || ''));
    if (m.method === 'Fetch.requestPaused') {
      const { requestId, request } = m.params;
      const remote = !request.url.startsWith(origin + '/') && !request.url.startsWith('data:');
      if (request.url.startsWith(RESEARCH_URL)) {
        const ticker = new URL(request.url).searchParams.get('ticker');
        const body = failResearch ? { message: 'Not Found' } : researchFixture(ticker);
        send('Fetch.fulfillRequest', { requestId, responseCode: failResearch ? 404 : 200,
          responseHeaders: [{ name: 'content-type', value: 'application/json' }, { name: 'access-control-allow-origin', value: '*' }],
          body: Buffer.from(JSON.stringify(body)).toString('base64') }).catch(() => {});
        return;
      }
      if (remote) externalRequests.push(request.url);
      if (remote || (failFixture && request.url.endsWith('/evidence-preview.json')) || (failCatalog && request.url.endsWith('/library-catalog.json'))) {
        send('Fetch.failRequest', { requestId, errorReason: 'BlockedByClient' }).catch(() => {});
      } else send('Fetch.continueRequest', { requestId }).catch(() => {});
    }
  };
  const { targetId } = await send('Target.createTarget', { url: 'about:blank' }, null);
  ({ sessionId: session } = await send('Target.attachToTarget', { targetId, flatten: true }, null));
  await send('Runtime.enable'); await send('Page.enable');
  await send('Fetch.enable', { patterns: [{ urlPattern: '*', requestStage: 'Request' }] });
  const evaluate = async expression => {
    const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || 'Browser evaluation failed');
    return r.result.value;
  };
  const waitFor = async expression => {
    for (let n = 0; n < 80; n++) { if (await evaluate(expression)) return; await sleep(100); }
    throw new Error(`Browser condition failed: ${expression}`);
  };
  const click = selector => evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
  const search = value => evaluate(`document.querySelector('#ed-search').value=${JSON.stringify(value)};document.querySelector('#ed-search').dispatchEvent(new Event('input'))`);
  const screenshot = async name => {
    await sleep(700);
    const { data } = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
    await writeFile(join(dir, name), Buffer.from(data, 'base64'));
  };

  const change = (selector, value) => evaluate(`{const el=document.querySelector(${JSON.stringify(selector)});el.value=${JSON.stringify(value)};el.dispatchEvent(new Event('change',{bubbles:true}));el.dispatchEvent(new Event('input',{bubbles:true}));}`);
  // Actual pointer clicks: fail if the control is hidden, covered or outside the viewport.
  const pointer = async selector => {
    await sleep(300);
    const point = await evaluate(`{const el=document.querySelector(${JSON.stringify(selector)});if(!el)throw Error('Missing control');el.scrollIntoView({block:'center',behavior:'instant'});const r=el.getBoundingClientRect();const x=r.x+r.width/2,y=r.y+r.height/2;if(!r.width||!r.height||!el.contains(document.elementFromPoint(x,y)))throw Error('Control is not reachable: '+${JSON.stringify(selector)});({x,y})}`);
    await send('Input.dispatchMouseEvent', {type:'mousePressed',...point,button:'left',clickCount:1});
    await send('Input.dispatchMouseEvent', {type:'mouseReleased',...point,button:'left',clickCount:1});
  };
  const navigate = path => send('Page.navigate', {url:origin+path});
  await send('Emulation.setDeviceMetricsOverride', {width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  // The chat is agent-only. The agent is simulated inside the page (before any module loads), so the check still
  // makes no network request; responses follow docs/api_contract.md as the deployed API returns them.
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `(() => {
    window.confirm = () => true;
    const jobs = new Map(); let n = 0;
    const json = (d, status = 200) => new Response(JSON.stringify(d), { status, headers: { 'Content-Type': 'application/json' } });
    const real = window.fetch.bind(window);
    window.fetch = async (url, o = {}) => {
      const u = String(url);
      if (!u.includes('execute-api') || !u.includes('/jobs')) return real(url, o);   // statistics go to the network (answered by the check)
      if (o.method === 'POST') { const id = '00000000-0000-4000-8000-' + String(++n).padStart(12, '0'); jobs.set(id, JSON.parse(o.body)); return json({ jobId: id, sessionId: 'session-check' }, 202); }
      const id = u.split('/').pop(), q = jobs.get(id)?.question || '';
      const diesel = /diesel/i.test(q);
      return json({ job_id: id, jobId: id, status: 'DONE', stage: 'done',
        stages: [{ stage: 'queued', t: '2026-11-15T23:39:02Z' }, { stage: 'agent_started', t: '2026-11-15T23:39:03Z' },
          { stage: diesel ? 'tool:search_evidence' : 'tool:get_portfolio_facts', t: '2026-11-15T23:39:05Z' }, { stage: 'guardrail', t: '2026-11-15T23:39:05Z' }, { stage: 'done', t: '2026-11-15T23:39:05Z' }],
        answer: { verdict: 'BROKEN', headline: 'Checked.', refusal: false, caveat: '2021–2026 · past behaviour · simulation · not advice',
          text: 'BROKEN — Answer to: ' + q + '\\n\\n- XIU.TO oil beta +0.011 [measured], 95% range -0.03 to +0.05 [measured].' + (diesel ? ' Diesel costs are passed through [1].' : '') + '\\n\\n2021–2026 · past behaviour · simulation · not advice' },
        trace: [{ step: 1, tool: diesel ? 'search_evidence' : 'get_portfolio_facts', input_summary: 'persona=robert', output_summary: diesel ? '1 passages' : 'bonds avg -0.17%', tag: diesel ? 'source' : 'measured', ms: 900 }],
        data: { risk_share: { rates: 0.71, stocks: 0.19, oil: 0.03 }, shields: [], cushion: [], betas: [], twin_series: [], stock_bond_series: [], scenario: null },
        citations: diesel ? [{ n: 1, evidence_id: 'CNQ-direct-1', excerpt: 'Diesel fuel costs', publisher: 'Canadian Natural', date: '2025', doc_type: 'annual report', trust: 'Issuer', url: 'https://www.cnrl.com/report.pdf' }] : [],
        toolCalls: [], durationMs: 2100 });
    };
  })()` });
  const view = () => evaluate('document.body.dataset.view');
  const shellIntact = async name => {
    assert.equal(await view(), name);
    assert.equal(await evaluate("getComputedStyle(document.querySelector('.topbar')).display !== 'none' && !!document.querySelector('#sidebar .app-nav')"), true, 'one shell, one navbar');
    assert.equal(await evaluate("document.querySelector('.app-nav [aria-current=page]')?.dataset.go"), name === 'portfolio' ? undefined : name);
  };

  // Landing: the agent.
  await navigate('/index.html');
  await waitFor("document.body?.dataset.view === 'agent' && document.querySelector('[data-suggest]')");
  assert.equal(await evaluate("document.querySelectorAll('dialog[open]').length"),0,'no forced signup');
  assert.equal(await evaluate("document.querySelector('#app').dataset.mode"),'agent');
  assert.match(await evaluate('document.title'),/RIPPLE AI/);
  await shellIntact('agent');
  await screenshot('agent-desktop.png');
  await pointer('.start-investigation');
  await waitFor("document.querySelector('.msg.assistant .verdict') && document.querySelector('#stop').hidden");
  assert.match(await evaluate("document.querySelector('.msg.assistant').textContent"),/bonds protect me/);
  await pointer('#tools-btn');
  await pointer('#tools-menu [data-tab=shock]');
  assert.equal(await evaluate("document.querySelectorAll('#tools-menu [name=shock]').length"),4);
  await change('#tools-menu [name=target]','XIU.TO');
  await pointer('#tools-menu [data-tool-ask]');
  await waitFor("document.querySelectorAll('.msg.assistant .verdict').length === 2 && document.querySelector('#stop').hidden");
  assert.match(await evaluate("[...document.querySelectorAll('.msg.assistant')].at(-1).textContent"),/30%/);

  // Statistics: same shell, backend data only.
  await pointer('.app-nav [data-go=statistics]');
  await waitFor("document.querySelectorAll('#stats-view .rank-row').length === 3");
  await shellIntact('statistics');
  assert.match(await evaluate('location.search'),/view=statistics/);
  assert.match(await evaluate("document.querySelector('#stats-view').textContent"),/Live backend/);
  await pointer('#stats-view [data-stats-ticker="TLT"]');
  await waitFor("document.querySelector('#stats-ticker-title')?.textContent.startsWith('TLT')");
  await screenshot('statistics-desktop.png');
  failResearch = true;
  await pointer('#stats-view [data-stats-ticker="XOM"]');
  await waitFor("document.querySelector('#stats-view .stats-error')");
  assert.match(await evaluate("document.querySelector('#stats-view .stats-error').textContent"),/not deployed yet/);
  assert.equal(await evaluate("document.querySelectorAll('#stats-view .rank-row').length"),0,'no local fallback');
  failResearch = false;
  await pointer('#stats-view [data-stats-retry]');
  await waitFor("document.querySelector('#stats-ticker-title')?.textContent.startsWith('XOM')");

  // Sources: the library fills the view.
  await pointer('.app-nav [data-go=sources]');
  await waitFor("document.querySelector('#rl-list .rl-source') && !document.querySelector('#rl-workspace').hidden");
  await shellIntact('sources');
  await screenshot('sources-desktop.png');

  // About: why it is useful, how the agent works, the shock example and the company disclosures.
  await pointer('.app-nav [data-go=about]');
  await waitFor("document.querySelector('#quotes-stage .q-card') && document.querySelector('#fuel-card canvas')");
  await shellIntact('about');
  assert.ok(!(await evaluate("document.querySelector('[data-view=about]').textContent")).includes('35 passages'), 'no counts at the top');
  await screenshot('about-desktop.png');
  await evaluate("document.querySelector('#quotes-stage .q-card').click()");
  await waitFor("document.body?.dataset.view === 'sources' && document.querySelector('#rl-list [aria-pressed=true]')");
  await evaluate('history.back()');
  await waitFor("document.body?.dataset.view === 'about'");

  // Account: my portfolio and saved portfolios, from the far-right menu.
  await pointer('#profile-btn');
  await pointer('#profile-menu [data-go=portfolio]');
  await waitFor("document.querySelector('#pf-title')");
  await shellIntact('portfolio');
  await pointer('[data-pf=save]');
  await waitFor("document.querySelectorAll('.pf-list li').length === 1");
  await pointer('.pf-list [data-pf=delete]');
  await waitFor("document.querySelector('.pf-empty')");
  await pointer('[data-pf=edit]');
  await pointer('#settings label:has([name=portfolio][value=custom])');
  await change('#settings [name=custom_name]','Research demo');
  await pointer('#settings [data-split]');
  await pointer('#settings [type=submit]');
  await waitFor("!document.querySelector('#settings').open && document.querySelector('#pf-current').textContent.includes('Research demo')");
  await pointer('[data-pf=save]');
  await waitFor("document.querySelectorAll('.pf-list li').length === 1");
  await screenshot('portfolio-desktop.png');
  await send('Page.reload',{ignoreCache:true});
  await waitFor("document.querySelector('#pf-current')?.textContent.includes('Research demo') && document.querySelectorAll('.pf-list li').length === 1");

  // Old explorer links land in the right view; deep links work.
  await navigate('/explorer.html?panel=evidence');
  await waitFor("document.body?.dataset.view === 'sources'");
  await navigate('/index.html?view=about');
  await waitFor("document.body?.dataset.view === 'about'");

  // Phone: the same shell, no horizontal scrolling in any view.
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  for (const v of ['agent', 'statistics', 'sources', 'about', 'portfolio']) {
    await navigate(`/index.html${v === 'agent' ? '' : `?view=${v}`}`);
    await waitFor(`document.body?.dataset.view === '${v}'`);
    await sleep(500);
    assert.ok(await evaluate('document.documentElement.scrollWidth <= innerWidth'), `no mobile overflow in ${v}`);
  }
  await screenshot('portfolio-mobile.png');
  await pointer('#sb-open');
  await pointer('.app-nav [data-go=statistics]');
  await waitFor("document.body?.dataset.view === 'statistics' && document.querySelector('#app').dataset.sidebar === 'closed'");
  await screenshot('statistics-mobile.png');
  assert.deepEqual(errors, []);
  assert.deepEqual(externalRequests, [],'no backend calls or external font requests');
  console.log(JSON.stringify({result:'PASS',checks:'one shell: agent landing, statistics (backend only, failure shown), sources, about (disclosures open sources), my portfolio + saved portfolios, back button, explorer redirects, deep links, mobile; no external requests',screenshots:dir}));
} finally {
  ws?.close(); chrome.kill('SIGTERM');
  await new Promise(resolve => { if (chrome.exitCode !== null) resolve(); else { chrome.once('exit', resolve); setTimeout(resolve, 2000); } });
  server.close(); await rm(profile, { recursive: true, force: true, maxRetries: 3 });
}
