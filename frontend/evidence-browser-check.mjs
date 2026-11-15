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
const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' };
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
    const { data } = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
    await writeFile(join(dir, name), Buffer.from(data, 'base64'));
  };
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: origin });
  await waitFor("document.querySelector('#evidence-desk')?.getAttribute('aria-busy') === 'false'");
  assert.equal(await evaluate("document.querySelectorAll('[data-company]').length"), 5);
  assert.match(await evaluate("document.querySelector('#ed-scope').textContent"), /35 passages/);
  assert.match(await evaluate("document.querySelector('#ed-reader').textContent"), /petroleum and chemicals commodity group/);
  assert.equal(await evaluate("document.querySelector('#network-section')"), null);
  await click('#evidence-open'); await screenshot('desktop.png');
  await click('[data-company="RY.TO"]'); await search('18,880');
  assert.match(await evaluate("document.querySelector('#ed-reader').textContent"), /Millions of Canadian dollars/);
  await click('[data-mode="expert"]'); await waitFor("document.querySelectorAll('#ed-reader details[open]').length === 2");
  await click('[data-company="CP.TO"]');
  assert.match(await evaluate("document.querySelector('#ed-reader').textContent"), /Source provenance pending/);
  await search('no-such-passage-xyz');
  assert.match(await evaluate("document.querySelector('#ed-passages').textContent"), /No matching passages/);
  await click('[data-clear-search]'); assert.equal(await evaluate("document.querySelectorAll('[data-passage]').length"), 8);
  await click('[data-mode="beginner"]');
  await click('[data-company="CNR.TO"]');
  // All acquired source types, including blocked entries and incomplete datasets.
  await waitFor("document.querySelector('#research-library').getAttribute('aria-busy') === 'false'");
  await click('[data-open-library]');
  assert.equal(await evaluate("document.querySelectorAll('[data-source]').length"), 52);
  await waitFor("document.querySelector('#rl-row-count')?.textContent.includes('65 / 65')");
  assert.match(await evaluate("document.querySelector('#rl-detail').textContent"), /100.02%/);
  const change = (id, value) => evaluate(`{const el=document.getElementById(${JSON.stringify(id)});el.value=${JSON.stringify(value)};el.dispatchEvent(new Event('change',{bubbles:true}));}`);
  const input = (id, value) => evaluate(`{const el=document.getElementById(${JSON.stringify(id)});el.value=${JSON.stringify(value)};el.dispatchEvent(new Event('input',{bubbles:true}));}`);
  await evaluate("{const el=document.querySelector('#rl-file');el.selectedIndex=2;el.dispatchEvent(new Event('change',{bubbles:true}));}");
  await waitFor("document.querySelector('#rl-detail').textContent.includes('100.04%')");
  assert.match(await evaluate("document.querySelector('#rl-data-table').textContent"), /2026-11-13/);
  await input('rl-row-query', 'CNR');
  assert.match(await evaluate("document.querySelector('#rl-row-count').textContent"), /1 \/ 65/);
  await click('[data-source="SRC-005"]');
  assert.match(await evaluate("document.querySelector('#rl-detail').textContent"), /No local file supplied/);
  assert.match(await evaluate("document.querySelector('#rl-detail').textContent"), /Recovery links & validation/);
  assert.match(await evaluate("document.querySelector('#rl-detail').textContent"), /Imported recovery suggestions are not verified citations/);
  await click('[data-source="SRC-021"]');
  await waitFor("document.querySelector('#rl-page-text')?.textContent.includes('Third Quarter 2026')");
  assert.match(await evaluate("document.querySelector('#rl-detail').textContent"), /Document identity reviewed locally/);
  assert.equal(await evaluate("document.querySelector('#rl-review-quarantine')"),null);
  await click('[data-source="SRC-027"]');
  await waitFor("document.querySelector('#rl-page-text')?.textContent.includes('FORTIS INC. REPORTS FOURTH QUARTER')");
  assert.equal(await evaluate("document.querySelectorAll('#rl-page option').length"),89);
  assert.match(await evaluate("document.querySelector('#rl-detail').textContent"), /2026-02-12/);
  await change('rl-status-filter', 'needs_attention');
  assert.equal(await evaluate("document.querySelectorAll('[data-source]').length"), expectedCatalog.summary.counts.needs_attention);
  await click('#rl-clear');
  // Open the exact hash/page associated with a reviewed CNR passage.
  await click('#ed-reader .rl-library-entry');
  await waitFor("document.querySelector('#rl-page-text')?.textContent.includes('petroleum')");
  await click('#rl-next-page');
  assert.equal(await evaluate("document.querySelector('#rl-page').selectedIndex > 0"), true);
  await screenshot('library-reader-desktop.png');
  await click('#rl-clear');
  await input('rl-text-query', 'diesel');
  await evaluate("document.querySelector('#rl-search-form').requestSubmit()");
  await waitFor("document.querySelector('#rl-search-progress').textContent.startsWith('Search complete')");
  assert.ok(await evaluate("document.querySelectorAll('#rl-search-results [data-library-hit]').length > 0"));
  assert.ok((await evaluate("document.querySelector('#rl-search-results').textContent")).includes(`${expectedCatalog.artifacts.filter(a=>a.quarantine&&['pdf','html'].includes(a.format)).length} quarantined`));
  await click('#rl-search-results [data-library-hit]');
  await waitFor("document.querySelector('#rl-page-text')?.textContent.toLowerCase().includes('diesel')");
  // Large fuel-price dataset, retaining units, dimensions and source status columns.
  await click('[data-source="SRC-037"]');
  await evaluate("{const el=document.querySelector('#rl-file');el.value=[...el.options].find(o=>o.textContent.startsWith('ZIP_CSV')).value;el.dispatchEvent(new Event('change',{bubbles:true}));}");
  await waitFor("document.querySelector('#rl-row-count')?.textContent.includes('46,262 / 46,262')");
  await evaluate("{const el=document.querySelector('[data-dimension=GEO]');el.value='Canada';el.dispatchEvent(new Event('change',{bubbles:true}));}");
  await change('rl-from','2026-09'); await change('rl-to','2026-09');
  assert.match(await evaluate("document.querySelector('#rl-data-table').textContent"), /Cents per litre/);
  assert.match(await evaluate("document.querySelector('#rl-data-table').textContent"), /STATUS/);
  assert.equal(await evaluate("document.querySelectorAll('#rl-data-table tbody tr').length > 0"),true);
  await click('[data-source="SRC-040"]');
  await evaluate("{const el=document.querySelector('#rl-file');el.value=[...el.options].find(o=>o.textContent.startsWith('TIME_SERIES')).value;el.dispatchEvent(new Event('change',{bubbles:true}));}");
  await waitFor("document.querySelector('#rl-row-count')?.textContent.includes('3,736 / 3,736')");
  await evaluate("{const el=document.querySelector('[data-dimension=series_id]');el.value='FXUSDCAD';el.dispatchEvent(new Event('change',{bubbles:true}));}");
  assert.match(await evaluate("document.querySelector('#rl-data-table').textContent"), /CAD per USD/);
  // Chat uses the same local search and preserves exact-source links.
  await change('answer-source','documents'); await input('question','diesel');
  await evaluate("document.querySelector('#question-form').requestSubmit()");
  await waitFor("document.querySelector('#answer [data-library-hit]') !== null");
  assert.match(await evaluate("document.querySelector('#answer').textContent"), /no AI call/);
  // CPKC remains quarantined in the general library.
  await click('[data-company="CP.TO"]'); await click('#ed-reader .rl-library-entry');
  await waitFor("document.querySelector('#rl-review-quarantine') !== null");
  await click('#rl-review-quarantine');
  await waitFor("document.querySelector('#rl-page-text') !== null");
  assert.match(await evaluate("document.querySelector('#rl-content').textContent"), /QUARANTINED/);
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await evaluate("document.querySelector('#rl-detail').scrollIntoView({behavior:'instant'})"); await sleep(150);
  const libraryWidths = await evaluate('({scroll:document.documentElement.scrollWidth, viewport:innerWidth})');
  assert.ok(libraryWidths.scroll <= 390 && libraryWidths.viewport <= 390, `Library overflow: ${JSON.stringify(libraryWidths)}`);
  await screenshot('library-mobile.png');
  await click('#evidence-open'); await sleep(150);
  const widths = await evaluate('({scroll:document.documentElement.scrollWidth, viewport:innerWidth})');
  assert.ok(widths.scroll <= 390 && widths.viewport <= 390, `Mobile overflow: ${JSON.stringify(widths)}`);
  await screenshot('mobile.png');
  await click('[data-passage][aria-pressed="true"]');
  assert.equal(await evaluate('document.activeElement.id'), 'ed-reader');
  await screenshot('mobile-reader.png');
  // Failure is explicit; no backend or invented fallback gets substituted.
  failFixture = true;
  await send('Page.reload', { ignoreCache: true });
  await waitFor("document.querySelector('#ed-retry')?.hidden === false");
  assert.match(await evaluate("document.querySelector('#ed-status').textContent"), /unavailable/);
  failFixture = false; await click('#ed-retry');
  await waitFor("document.querySelectorAll('[data-company]').length === 5");
  failCatalog = true; await send('Page.reload', { ignoreCache: true });
  await waitFor("document.querySelector('#rl-retry')?.hidden === false");
  assert.match(await evaluate("document.querySelector('#rl-status').textContent"), /unavailable/);
  failCatalog = false; await click('#rl-retry');
  await waitFor("document.querySelectorAll('[data-source]').length === 52");
  assert.deepEqual(errors, []); assert.deepEqual(externalRequests, []);
  console.log(JSON.stringify({ result: 'PASS', checks: 'evidence desk, 52 sources, both XIU dates, blocked sources, exact-page linkage, full-text search, fuel and FX datasets, local chat search, quarantine, mobile, load failures/retry, no external requests or JS exceptions', screenshots: dir }));
} finally {
  ws?.close(); chrome.kill('SIGTERM');
  await new Promise(resolve => { if (chrome.exitCode !== null) resolve(); else { chrome.once('exit', resolve); setTimeout(resolve, 2000); } });
  server.close(); await rm(profile, { recursive: true, force: true, maxRetries: 3 });
}
