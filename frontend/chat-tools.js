// Pure helpers behind the chat's tools: question builders, the portfolio snapshot, conversation search,
// the command palette and Markdown export. No DOM, no network; every number comes from the saved tables.
import { CORE_TICKERS, TICKER_INFO, SHOCKS } from './config.js';
import { finite, shortTicker } from './formatters.js';
import { PERSONAS, portfolioRows, weightedBeta, shockImpact } from './workspace-store.js';

// Tools the deployed agent offers beyond oil (docs/api_contract.md, lambdas/tools): shields, protection, rates.
export const SHIELDS = Object.freeze([
  { value: 'GLD', label: 'Gold (GLD)' }, { value: 'ZST.TO', label: 'Short-term bonds (ZST.TO)' },
  { value: 'XBB.TO', label: 'Canadian bonds (XBB.TO)' }, { value: 'AGG', label: 'US bonds (AGG)' },
  { value: 'TLT_usd', label: 'Long US Treasuries in USD (TLT)' }, { value: 'usdcad', label: 'US dollar (USD/CAD)' },
]);
export const RATE_MOVES = Object.freeze([-100, -50, 50, 100, 200]);
export const PROTECTION_ASKS = Object.freeze({
  bonds: 'Did my bonds protect me in my worst weeks?',
  risk: 'How much of my portfolio’s risk comes from rates, stocks and oil?',
  drawdown: 'What was my worst drawdown, and what cushioned it?',
  currency: 'Did the US dollar cushion my portfolio’s worst weeks?',
});
/** Starter questions for the home screen, matched to what the agent's tools cover. */
export const suggestions = () => [
  PROTECTION_ASKS.bonds,
  'What happens to my portfolio if interest rates rise 100 bp?',
  'Is gold a shield for my portfolio?',
  PROTECTION_ASKS.risk,
];

export const EVIDENCE_TOPICS = Object.freeze(['diesel', 'fuel surcharge', 'credit', 'pipeline', 'jet fuel', 'carbon']);
export const TICKER_ASKS = Object.freeze({
  beta: t => `What is ${shortTicker(t)}’s oil beta?`,
  reliable: t => `How reliable is ${shortTicker(t)}’s oil beta?`,
  why: t => `Why is ${shortTicker(t)} exposed to oil?`,
});

/** Turn a tool's settings into a plain-language question the chat (agent or offline) understands. */
export function toolQuestion(tool, opts = {}) {
  if (tool === 'shock') {
    const s = Number(opts.shock);
    if (!SHOCKS.includes(s)) throw Error('Choose a ±15% or ±30% Brent move.');
    const target = opts.ticker && CORE_TICKERS.includes(opts.ticker) ? shortTicker(opts.ticker) : 'my portfolio';
    return `What happens to ${target} if Brent ${s < 0 ? 'drops' : 'rises'} ${Math.abs(s)}% in a week?`;
  }
  if (tool === 'ticker') {
    if (!CORE_TICKERS.includes(opts.ticker)) throw Error('Choose a ticker with saved data.');
    return (TICKER_ASKS[opts.ask] ?? TICKER_ASKS.beta)(opts.ticker);
  }
  if (tool === 'evidence') {
    const topic = EVIDENCE_TOPICS.includes(opts.topic) ? opts.topic : 'diesel';
    return `What do the companies say about ${topic}?`;
  }
  if (tool === 'exposure') return 'How exposed is my portfolio to oil?';
  if (tool === 'rates') {
    const bp = Number(opts.bp);
    if (!RATE_MOVES.includes(bp)) throw Error('Choose a rate move of ±50, ±100 or +200 bp.');
    return `What happens to my portfolio if interest rates ${bp < 0 ? 'fall' : 'rise'} ${Math.abs(bp)} bp?`;
  }
  if (tool === 'shield') {
    const s = SHIELDS.find(x => x.value === opts.shield);
    if (!s) throw Error('Choose a shield to test.');
    return `Is ${s.label} a shield in my portfolio’s worst weeks?`;
  }
  if (tool === 'protect') return PROTECTION_ASKS[opts.ask] ?? PROTECTION_ASKS.bonds;
  throw Error(`Unknown tool: ${tool}`);
}

/** Snapshot of the profile's portfolio from the saved betas. Null until the tables are loaded. */
export function portfolioSnapshot(tables, workspace) {
  const holdings = portfolioRows(tables, workspace);
  if (!holdings.length) return null;
  const beta = tables?.sensitivities ? weightedBeta(tables, holdings) : null;
  const name = workspace.portfolio === 'custom' ? workspace.custom?.name || 'My portfolio' : `${PERSONAS[workspace.portfolio]?.name ?? 'Sample'}’s sample`;
  const top = [...holdings].sort((a, b) => b.weight - a.weight).slice(0, 4).map(h => ({ ticker: shortTicker(h.ticker), weight: h.weight }));
  const down = finite(beta) ? shockImpact(beta, -30) : null;
  const capital = finite(workspace.capital) ? workspace.capital : null;
  return { name, count: holdings.length, beta: finite(beta) ? beta : null, top,
    downPct: finite(down) ? down : null, downMoney: finite(down) && capital ? capital * down / 100 : null, capital };
}

/** Case- and accent-insensitive search over conversation titles and message text. */
const fold = s => String(s ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
export function searchChats(chats, query) {
  const q = fold(query).trim();
  if (!q) return chats.map(c => ({ id: c.id, title: c.title, match: null }));
  const words = q.split(/\s+/);
  return chats.flatMap(c => {
    const title = fold(c.title);
    const bodies = (c.messages ?? []).map(m => m.text ?? m.answer ?? '');
    const hit = bodies.find(b => words.every(w => fold(b).includes(w)));
    if (!words.every(w => title.includes(w)) && !hit) return [];
    let match = null;
    if (hit && !words.every(w => title.includes(w))) {
      const i = fold(hit).indexOf(words[0]);
      match = `${i > 30 ? '…' : ''}${hit.slice(Math.max(0, i - 30), i + 60).replace(/\s+/g, ' ').trim()}…`;
    }
    return [{ id: c.id, title: c.title, match }];
  });
}

/** Command palette: rank commands and conversations against the typed text. */
export function paletteResults(commands, chats, query, limit = 9) {
  const q = fold(query).trim();
  const score = text => {
    const t = fold(text);
    if (!q) return 1;
    if (t.startsWith(q)) return 3;
    if (t.includes(q)) return 2;
    let i = 0;
    for (const ch of t) if (ch === q[i]) i++;
    return i === q.length ? 1 : 0;
  };
  const cmds = commands.filter(c => !c.hidden).map(c => ({ ...c, kind: 'command', score: score(`${c.label} ${c.keywords ?? ''}`) }));
  const convs = chats.map(c => ({ id: `chat:${c.id}`, chatId: c.id, label: c.title, kind: 'chat', score: q ? score(c.title) : 0.5 }));
  return [...cmds, ...convs].filter(r => r.score > 0).sort((a, b) => b.score - a.score).slice(0, limit);
}

/** Markdown export of one conversation. Text only; nothing is fetched or invented. */
export function chatToMarkdown(chat, { now = new Date() } = {}) {
  const lines = [`# ${chat.title || 'Conversation'}`, '', `_Exported from RIPPLE AI on ${now.toISOString().slice(0, 10)}. Historical relationships from weekly data, not forecasts or investment advice._`, ''];
  for (const m of chat.messages ?? []) {
    if (m.role === 'user') { lines.push(`## You`, '', m.text, ''); continue; }
    const tag = m.kind === 'agent' ? 'RIPPLE AI agent' : m.kind === 'error' ? 'RIPPLE AI (no answer)' : 'RIPPLE AI local preview (saved data, no AI)';
    lines.push(`## ${tag}`, '', ...(m.verdict ? [`**${m.verdict}**`, ''] : []), m.kind === 'agent' ? m.answer : m.text, '', ...(m.caveat ? [`_${m.caveat}_`, ''] : []));
    if (m.table) {
      lines.push(`| ${m.table.head.join(' | ')} |`, `|${m.table.head.map(() => ' --- ').join('|')}|`, ...m.table.rows.map(r => `| ${r.join(' | ')} |`), '');
    }
    for (const q of m.quotes ?? []) lines.push(`> ${q.text}`, `> — ${q.ticker} ${q.issuer}, ${q.section}, PDF p. ${q.page} (${q.id})`, '');
    for (const c of m.citations ?? []) lines.push(`> ${c.n ? `[${c.n}] ` : ''}${c.excerpt || c.text || 'No passage supplied.'}`, `> — ${[c.ticker, c.publisher, c.date, c.section, c.url || c.source_url].filter(Boolean).join(', ')}`, '');
  }
  return `${lines.join('\n').trim()}\n`;
}

export const tickerOptions = () => CORE_TICKERS.map(t => ({ value: t, label: `${shortTicker(t)} · ${TICKER_INFO[t].name}` }));
