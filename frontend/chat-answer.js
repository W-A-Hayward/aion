// Offline answers for the chat when the backend agent is not connected. Pure functions over the local
// tables (preview-data.json) and passages (evidence-preview.json): no AI, no network, every number comes
// from a saved table. Each answer lists the steps actually taken, so the user can see how it was built.
import { CORE_TICKERS, TICKER_INFO, SHOCKS } from './config.js';
import { finite, number, interval, probability, shortTicker } from './formatters.js';
import { PERSONAS, portfolioRows, contributions, weightedBeta, shockImpact } from './workspace-store.js';

const ALIASES = Object.fromEntries(CORE_TICKERS.flatMap(t => {
  const name = TICKER_INFO[t].name.toLowerCase();
  const first = name.split(/[\s(]/)[0];
  const extra = { 'RY.TO': ['rbc', 'royal bank'], 'ENB.TO': ['enbridge'], XOM: ['exxon'], 'ATD.TO': ['couche-tard', 'couche tard'],
    'SHOP.TO': ['shopify'], 'XIU.TO': ['tsx 60', 'tsx60'] }[t] || [];
  return [[shortTicker(t).toLowerCase(), t], [t.toLowerCase(), t], ...(first.length > 4 && !['ishares', 'vanguard', 'spdr', 'invesco'].includes(first) ? [[first, t]] : []), ...extra.map(a => [a, t])];
}));

export function findTickers(question) {
  const q = ` ${question.toLowerCase().replace(/[^a-z0-9.&\- ]/g, ' ')} `;
  const found = new Set();
  for (const [alias, ticker] of Object.entries(ALIASES)) if (q.includes(` ${alias} `)) found.add(ticker);
  return [...found];
}

export function findShock(question) {
  const m = question.replace('−', '-').match(/([+-]?\d{1,3})\s*%/);
  if (!m) return null;
  let v = Number(m[1]);
  if (!m[1].startsWith('-') && !m[1].startsWith('+') && /\b(drops?|dropp\w*|falls?|fell|crash\w*|down|declin\w*|plung\w*|sinks?|tumbl\w*|baisse)\b/i.test(question)) v = -v;
  return v;
}

const pct = (v, d = 2) => (finite(v) ? `${number(v, d, true)}%` : 'unavailable');
const money = v => (finite(v) ? `${v < 0 ? '−' : '+'}$${Math.abs(v).toLocaleString('en-CA', { maximumFractionDigits: 0 })}` : 'unavailable');
const direction = r => (r.lo_simple > 0 ? 'tended to rise with oil' : r.hi_simple < 0 ? 'tended to fall when oil rose' : 'has no settled direction (the range crosses zero)');

function tickerBlock(row, tables, question, shock) {
  const t = shortTicker(row.ticker), info = TICKER_INFO[row.ticker];
  const lines = [`**${t}** (${info.name}) has a weekly Brent beta of **${number(row.beta_simple, 3, true)}**, 95% range ${interval(row.lo_simple, row.hi_simple)}, over ${number(row.n_weeks, 0)} weeks. Historically it ${direction(row)}.`];
  if (/reliab|confiden|stable|sure|uncertain|trust|signific/i.test(question)) {
    lines.push(`p = ${probability(row.p_simple)}${finite(row.q_simple) ? `, q = ${probability(row.q_simple)} after multiple-testing correction` : ''}. Leaving out 2022, p = ${probability(row.p_ex2022)}. Out-of-sample direction hit rate: ${finite(row.oos_hit_rate) ? `${Math.round(row.oos_hit_rate * 100)}% of ${number(row.oos_n, 0)} windows` : 'not supplied'}.`);
  }
  const chain = tables.chain_reconciliation.find(c => c.ticker === row.ticker);
  if (chain && /why|how|where|come from|channel|path|explain/i.test(question)) {
    lines.push(`One measured route: ${chain.chain}, which accounts for about ${Math.round(chain.share_explained * 100)}% of the direct beta. That is a statistical pathway, not a proven cause.`);
  }
  const s = SHOCKS.includes(shock) ? shock : null;
  if (s !== null) lines.push(`If Brent moves ${s > 0 ? '+' : ''}${s}% in a week and the historical beta held, ${t} would move about **${pct(shockImpact(row.beta_simple, s))}** (range ${pct(shockImpact(row.lo_simple, s))} to ${pct(shockImpact(row.hi_simple, s))}).`);
  return lines.join('\n\n');
}

function portfolioBlock(tables, workspace, shock) {
  const holdings = portfolioRows(tables, workspace);
  if (!holdings.length) return { text: 'Your profile has no portfolio yet. Add one from the profile menu.', table: null };
  const rows = contributions(tables, holdings).sort((a, b) => Math.abs(b.contribution ?? 0) - Math.abs(a.contribution ?? 0));
  const beta = weightedBeta(tables, holdings);
  const name = workspace.portfolio === 'custom' ? workspace.custom.name : `${PERSONAS[workspace.portfolio].name}’s sample portfolio`;
  const top = rows[0];
  const s = SHOCKS.includes(shock) ? shock : 30;
  const impact = shockImpact(beta, s);
  const lines = [`**${name}**: weighted oil beta of about **${number(beta, 3, true)}**. The biggest contributor is ${shortTicker(top.ticker)} (${Math.round(top.weight * 100)}% of the portfolio, beta ${number(top.beta, 3, true)}).`,
    `For a ${s > 0 ? '+' : ''}${s}% Brent week, that implies roughly **${pct(impact)}**, or **${money(workspace.capital * impact / 100)}** on $${workspace.capital.toLocaleString('en-CA')}.`];
  const reg = workspace.portfolio !== 'custom' && tables.portfolio_beta.find(p => p.persona === workspace.portfolio);
  if (reg) lines.push(`The saved regression for this sample gives ${number(reg.beta, 3, true)} (95% range ${interval(reg.lo, reg.hi)}). It uses an earlier method, so treat it as a legacy figure.`);
  lines.push('The weighted beta is a proxy: it adds up each holding’s beta and has no confidence range of its own.');
  return {
    text: lines.join('\n\n'),
    table: { head: ['Holding', 'Weight', 'Beta', '95% range', 'Contribution'],
      rows: rows.map(r => [shortTicker(r.ticker), `${number(r.weight * 100, 1)}%`, number(r.beta, 3, true), interval(r.lo, r.hi), number(r.contribution, 4, true)]) },
  };
}

const STOP = new Set('the a an and or of to in on for is are what how why does do with my me i it its this that which about from by be as at oil'.split(' '));
export function searchPassages(passages, question, limit = 3) {
  const terms = question.toLowerCase().match(/[a-zà-ÿ]{3,}/g)?.filter(w => !STOP.has(w)) ?? [];
  const wanted = findTickers(question);
  return passages.map(p => {
    const hay = `${p.excerpt_original} ${p.section} ${p.operational_channel}`.toLowerCase();
    let score = terms.reduce((s, w) => s + (hay.includes(w) ? 1 : 0), 0);
    if (wanted.includes(p.subject_ticker)) score += 2;
    return { p, score };
  }).filter(x => x.score > 0).sort((a, b) => b.score - a.score).slice(0, limit).map(x => x.p);
}

/** Returns { steps: string[], text: string (light markdown: **bold**, paragraphs), table?, quotes? } */
export function answerLocally(question, { tables, workspace, evidence }) {
  const steps = [];
  const tickers = findTickers(question);
  const shock = findShock(question);
  const wantsDocs = /evidence|document|report|disclos|quote|source|diesel|fuel|surcharge|credit|pipeline|annual/i.test(question);
  const aboutOil = /oil|brent|crude|exposure|exposed|beta|shock|risk|sensitiv|petrole|pétrole/i.test(question);
  const wantsPortfolio = /portfolio|portefeuille|my (holdings|exposure|money|investments?)|\bme\b|\bmy\b|i own|i hold/i.test(question) || (!tickers.length && !wantsDocs && aboutOil);
  const parts = [];
  let table = null, quotes = null;
  if (shock !== null && !SHOCKS.includes(shock)) parts.push(`Only ±15% and ±30% Brent shocks are modelled, so I can’t compute ${shock}%. I used ${shock < 0 ? '−30' : '+30'}% instead.`);
  const usedShock = shock === null ? null : SHOCKS.includes(shock) ? shock : shock < 0 ? -30 : 30;

  if (tickers.length) {
    steps.push(`Looked up the saved Brent sensitivities for ${tickers.map(shortTicker).join(', ')}`);
    for (const t of tickers.slice(0, 4)) {
      const row = tables.sensitivities.find(r => r.ticker === t);
      parts.push(row && finite(row.beta_simple) ? tickerBlock(row, tables, question, usedShock) : `No usable estimate is saved for ${shortTicker(t)}.`);
    }
    if (usedShock !== null) steps.push(`Applied the ${usedShock > 0 ? '+' : ''}${usedShock}% shock formula 100 × (exp(β × ln(1 + s)) − 1)`);
  } else if (wantsPortfolio) {
    steps.push('Read your portfolio from your profile');
    steps.push('Combined each holding’s saved beta into a weighted beta');
    const block = portfolioBlock(tables, workspace, usedShock);
    parts.push(block.text); table = block.table;
  }
  if (wantsDocs && evidence) {
    steps.push(`Searched ${evidence.passages.length} annual-report passages from XIU constituents`);
    quotes = searchPassages(evidence.passages, question).map(p => ({ ticker: shortTicker(p.subject_ticker), id: p.research_id, page: p.pdf_page,
      section: p.section, text: p.excerpt_original, issuer: evidence.documents.find(d => d.document_id === p.document_id)?.issuer || '' }));
    parts.push(quotes.length ? 'Here is what the companies wrote. These passages describe how oil reaches each business; they don’t say which way the shares move.'
      : 'No passage matched. The local set covers RBC, CNQ, CPKC, CN and Couche-Tard; try words like diesel, fuel surcharge or credit.');
  }
  if (!parts.length) parts.push('I can answer from the saved data: a ticker’s oil beta and how reliable it is, a ±15% or ±30% Brent shock, your portfolio’s exposure, or what the companies wrote about fuel and oil.');
  return { steps, text: parts.join('\n\n'), table, quotes };
}

export function suggestions(workspace) {
  const own = workspace.portfolio === 'custom' ? workspace.custom.holdings : null;
  const first = own?.[0]?.ticker;
  return [
    'How exposed is my portfolio to oil?',
    'What happens to my portfolio if Brent drops 30%?',
    first ? `How reliable is ${shortTicker(first)}’s oil beta?` : 'How reliable is XIU’s oil beta?',
    'What do the companies say about diesel?',
  ];
}
