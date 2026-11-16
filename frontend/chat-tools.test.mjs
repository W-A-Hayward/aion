import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { toolQuestion, portfolioSnapshot, searchChats, paletteResults, chatToMarkdown, EVIDENCE_TOPICS } from './chat-tools.js';

const robert = { profile: { name: 'R', experience: 'beginner' }, portfolio: 'robert', capital: 10000 };

test('tool questions are plain questions the agent routes to its tools', () => {
  for (const shock of [-30, -15, 15, 30]) assert.match(toolQuestion('shock', { shock }), new RegExp(`Brent ${shock < 0 ? 'drops' : 'rises'} ${Math.abs(shock)}%`));
  assert.throws(() => toolQuestion('shock', { shock: 20 }), /±15% or ±30%/);
  assert.match(toolQuestion('shock', { shock: -15, ticker: 'ENB.TO' }), /^What happens to ENB if Brent drops 15%/);
  for (const ask of ['beta', 'reliable', 'why']) assert.match(toolQuestion('ticker', { ticker: 'XIU.TO', ask }), /XIU/);
  assert.throws(() => toolQuestion('ticker', { ticker: 'FAKE' }));
  for (const topic of EVIDENCE_TOPICS) assert.match(toolQuestion('evidence', { topic }), new RegExp(topic));
  assert.equal(toolQuestion('exposure'), 'How exposed is my portfolio to oil?');
});
test('the portfolio card needs no local statistics: sample weights come from compute/stats.py PERSONAS', () => {
  const snap = portfolioSnapshot(null, robert);
  assert.equal(snap.name, 'Robert’s sample');
  assert.equal(snap.count, 4);
  assert.deepEqual(snap.top.map(h => [h.ticker, h.weight]), [['XBB', 0.4], ['TLT', 0.3], ['ENB', 0.15], ['RY', 0.15]]);
  assert.equal(snap.beta, null, 'no beta is computed in the browser');
  const custom = { ...robert, portfolio: 'custom', custom: { name: 'Mine', holdings: [{ ticker: 'XIU.TO', weight: 1 }] } };
  assert.equal(portfolioSnapshot(null, custom).name, 'Mine');
  assert.equal(portfolioSnapshot(null, { ...robert, portfolio: 'custom', custom: { holdings: [] } }), null);
});

test('conversation search matches titles and message text, ignoring case and accents', () => {
  const all = [
    { id: 'a', title: 'Enbridge pipeline', messages: [] },
    { id: 'b', title: 'Second', messages: [{ role: 'assistant', text: 'The weighted beta of the Pétrole portfolio is small.' }] },
  ];
  assert.equal(searchChats(all, '').length, 2);
  assert.deepEqual(searchChats(all, 'ENBRIDGE').map(c => c.id), ['a']);
  const hit = searchChats(all, 'petrole');
  assert.deepEqual(hit.map(c => c.id), ['b']);
  assert.match(hit[0].match, /Pétrole/);
  assert.equal(searchChats(all, 'nothing here').length, 0);
});

test('command palette ranks prefix matches first and hides hidden commands', () => {
  const cmds = [{ id: 'n', label: 'New chat' }, { id: 'x', label: 'Export conversation' }, { id: 'h', label: 'Hidden', hidden: true }];
  const chats = [{ id: 'c1', title: 'Export taxes question' }];
  const r = paletteResults(cmds, chats, 'exp');
  assert.equal(r[0].id, 'x');
  assert.ok(r.some(x => x.chatId === 'c1'));
  assert.ok(!paletteResults(cmds, chats, '').some(x => x.id === 'h'));
  assert.deepEqual(paletteResults(cmds, chats, 'nc').map(x => x.id), ['n'], 'fuzzy subsequence');
});

test('markdown export keeps text, tables and sources without adding anything', () => {
  const md = chatToMarkdown({ title: 'XIU', messages: [
    { role: 'user', text: 'How reliable is XIU?' },
    { role: 'assistant', kind: 'local', text: '**XIU** beta', table: { head: ['A', 'B'], rows: [['1', '2']] }, quotes: [{ text: 'Q', ticker: 'CNQ', issuer: 'CNRL', section: 'MD&A', page: 4, id: 'R1' }] },
    { role: 'assistant', kind: 'agent', answer: 'Agent says', citations: [{ text: 'cited', ticker: 'RY' }] },
  ] }, { now: new Date('2026-11-15T00:00:00Z') });
  assert.match(md, /^# XIU/);
  assert.match(md, /2026-11-15/);
  assert.match(md, /\| A \| B \|\n\| --- \| --- \|\n\| 1 \| 2 \|/);
  assert.match(md, /> Q\n> — CNQ CNRL, MD&A, PDF p\. 4 \(R1\)/);
  assert.match(md, /## RIPPLE AI agent\n\nAgent says/);
  assert.match(md, /not forecasts or investment advice/);
});

test('the chat stylesheet has no orange left', async () => {
  for (const file of ['chat.css', 'investigation-progress.css', 'index.html']) {
    const text = await readFile(new URL(`./${file}`, import.meta.url), 'utf8');
    assert.doesNotMatch(text, /e2801f|e98a2c|fdf1e2|9a4f00/i, file);
  }
});

test('agent answers render a safe Markdown subset', async () => {
  const { renderMarkdown } = await import('./safe-markdown.js');
  const html = renderMarkdown('Intro **bold** and `beta`.\n\n- one\n- *two*\n\n1. first\n2. second\n\n## Heading\n<script>alert(1)</script> & "x"');
  assert.match(html, /<p>Intro <strong>bold<\/strong> and <code>beta<\/code>\.<\/p>/);
  assert.match(html, /<ul><li>one<\/li><li><em>two<\/em><\/li><\/ul>/);
  assert.match(html, /<ol><li>first<\/li><li>second<\/li><\/ol>/);
  assert.match(html, /<p class="md-h">Heading<\/p>/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt; &amp; &quot;x&quot;/);
  assert.equal(renderMarkdown('a\nb'), '<p>a<br>b</p>');
  assert.equal(renderMarkdown('2 * 3 * 4 = 24'), '<p>2 * 3 * 4 = 24</p>', 'arithmetic is not italicised');
});

test('general tools: rate scenarios, shields and protection questions', async () => {
  const { RATE_MOVES, SHIELDS, PROTECTION_ASKS, suggestions } = await import('./chat-tools.js');
  assert.equal(toolQuestion('rates', { bp: 100 }), 'What happens to my portfolio if interest rates rise 100 bp?');
  assert.equal(toolQuestion('rates', { bp: -50 }), 'What happens to my portfolio if interest rates fall 50 bp?');
  assert.throws(() => toolQuestion('rates', { bp: 37 }));
  assert.ok(RATE_MOVES.every(bp => bp !== 0 && Math.abs(bp) <= 300), 'within the tools Lambda range');
  assert.equal(toolQuestion('shield', { shield: 'GLD' }), 'Is Gold (GLD) a shield in my portfolio’s worst weeks?');
  assert.throws(() => toolQuestion('shield', { shield: 'BTC' }));
  assert.deepEqual(SHIELDS.map(s => s.value), ['GLD', 'ZST.TO', 'XBB.TO', 'AGG', 'TLT_usd', 'usdcad'], 'lambdas/tools SHIELD_ORDER');
  assert.equal(toolQuestion('protect', { ask: 'risk' }), PROTECTION_ASKS.risk);
  assert.equal(suggestions().length, 4);
  assert.ok(suggestions().some(q => /rates/.test(q)) && suggestions().some(q => /bonds/.test(q)), 'home suggestions are not oil-only');
});

test('measured results card from the contract data object', async () => {
  const { compactData, renderAnswerData } = await import('./answer-data.js');
  const data = { risk_share: { rates: 0.31, stocks: 0.42, oil: 0.02 }, shields: [{ item: 'GLD', label: 'WORKING', avg_pct_worst: 0.4, weeks_up: 17, weeks: 27 }],
    cushion: [{ asset: 'usdcad', avg_return_pct: 0.6, hit_weeks: 19, n_weeks: 27 }], betas: [{ subject: 'robert', beta: -0.03, lo: -0.051, hi: -0.009 }],
    twin_series: new Array(60).fill({ week: 'x' }), stock_bond_series: [], scenario: { subject: 'robert', subject_type: 'persona', shock_pct: 30, impact_pct: -0.782, lo_pct: -1.338, hi_pct: -0.223 } };
  const c = compactData(data);
  assert.equal(JSON.stringify(c).length < 2000, true, 'small enough to keep with the message');
  const html = renderAnswerData(c);
  assert.match(html, /Robert’s portfolio · Brent \+30%/);
  assert.match(html, /-0\.78%/);
  assert.match(html, /95% range -1\.34% to -0\.22%/);
  assert.match(html, /Rates<\/span><span class="ad-track"><i style="width:31%/);
  assert.match(html, /do not add up/);
  assert.match(html, /Gold \(GLD\)<\/td><td><span class="verdict mini" data-verdict="working">WORKING/);
  assert.match(html, /US dollar \(USD\/CAD\)<\/td><td>\+0\.60%<\/td><td>19 of 27/);
  assert.equal(renderAnswerData({ risk_share: {}, shields: [], cushion: [], betas: [], scenario: null }), '');
  assert.equal(compactData(null), null);
  assert.doesNotMatch(renderAnswerData({ shields: [{ item: '<img src=x onerror=1>', label: '<b>' }] }), /<img|<b>/);
});

test('drawdown and stock–bond series become small charts; empty series draw nothing', async () => {
  const { compactData, renderAnswerData, lineChart } = await import('./answer-data.js');
  const data = { twin_series: [{ week: '2021-11', own_dd_pct: 0, twin_dd_pct: null }, { week: '2022-06', own_dd_pct: -12.4, twin_dd_pct: null }, { week: '2022-12', own_dd_pct: -5, twin_dd_pct: null }],
    stock_bond_series: [{ pair: 'XIU.TO/XBB.TO', measure: 'cpi_ge_3', correlation: 0.42, n_weeks: 129, week: null }, { pair: 'XIU.TO/XBB.TO', measure: 'cpi_lt_3', correlation: 0.07, n_weeks: 82, week: null },
      { pair: 'SPY/TLT', measure: 'rolling_52w', week: '2022-11', correlation: 0.3, n_weeks: 52 }, { pair: 'SPY/TLT', measure: 'rolling_52w', week: '2022-12', correlation: -0.1, n_weeks: 52 }],
    shields: [{ item: 'usdcad', label: 'NEUTRAL', avg_pct_worst: 0.02, weeks_up: 14, weeks: 27, contribution_per_100k: 5.53 }] };
  const html = renderAnswerData(compactData(data));
  assert.equal((html.match(/<svg/g) || []).length, 2);
  assert.match(html, /Deepest drawdown -12\.40% \(2022-06\)/);
  assert.match(html, /Inflation ≥ 3%[\s\S]*\+0\.42 <small>\(129 wk\)/);
  assert.match(html, /Per \$100k[\s\S]*\+\$6/);
  assert.match(html, /role="img" aria-label="Drawdown chart/);
  assert.doesNotMatch(html, /Alternative twin/, 'an all-empty twin series is not drawn or listed');
  assert.equal(lineChart([{ name: 'x', cls: 'own', points: [{ x: 'a', y: 1 }] }]), '', 'one point is not a chart');
});

