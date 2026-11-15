import { escapeHTML as esc, finite, hasEstimate, nodeLabel, number, shortTicker } from './formatters.js';
import { TICKER_INFO } from './config.js';

const FACTORS = ['us10y', 'ca10y', 'ca2y', 'usdcad', 'breakeven'];

// A graph view model, not a financial table. Hypotheses are created only by the user.
export function buildNetwork(tables, ticker, { macroContext = true, hypothesis = false } = {}) {
  const sensitivity = tables.sensitivities.find(row => row.ticker === ticker);
  const edges = [];
  if (hasEstimate(sensitivity)) edges.push({
    id: 'direct', from: 'oil', to: ticker, kind: 'measured', source: 'sensitivities',
    beta: sensitivity.beta_simple, lo: sensitivity.lo_simple, hi: sensitivity.hi_simple,
    p: sensitivity.p_simple, n: sensitivity.n_weeks, unit: 'CAD log return per Brent log return',
    note: 'The total historical association. This is not a direct causal channel or an energy-sector allocation.',
  });
  const bridges = tables.links.filter(row => row.to_node === ticker && FACTORS.includes(row.from_node));
  const needed = new Set(bridges.map(row => row.from_node));
  const links = tables.links.filter(row => (row.to_node === ticker && FACTORS.includes(row.from_node))
    || (row.from_node === 'oil' && FACTORS.includes(row.to_node) && (macroContext || needed.has(row.to_node))));
  for (const row of links) {
    if (![row.beta, row.lo, row.hi].every(finite) || row.lo > row.beta || row.beta > row.hi) continue;
    edges.push({ id: `link:${row.link_id}`, from: row.from_node, to: row.to_node, kind: 'measured',
      source: 'links', beta: row.beta, lo: row.lo, hi: row.hi, p: row.p, unit: row.unit,
      note: row.to_node === ticker ? 'A separate regression, not proof of a causal transmission mechanism.'
        : 'Measured macro context. This alone does not establish a pathway to the selected ticker.',
    });
  }
  for (const row of tables.edges.filter(row => row.edge_type === 'cited' && row.to_node === ticker && row.from_node === 'oil')) {
    edges.push({ id: `cited:${row.evidence_id}`, from: row.from_node, to: row.to_node,
      kind: 'cited', source: 'edges', evidence_id: row.evidence_id,
      note: 'A document-supported pathway is not a numerical estimate or proof of causality.',
    });
  }
  // Supported evidence records can be inspected even if a backend omits the optional edges table.
  for (const row of tables.evidence.filter(row => row.ticker === ticker)) {
    if (edges.some(edge => edge.evidence_id === row.evidence_id)) continue;
    edges.push({ id: `cited:${row.evidence_id}`, from: 'oil', to: ticker, kind: 'cited',
      source: 'evidence', evidence_id: row.evidence_id,
      note: 'Documentary context. A citation does not quantify a holding’s contribution.',
    });
  }
  const hypothesisFactor = FACTORS.find(factor => !bridges.some(row => row.from_node === factor)) || 'ca10y';
  if (hypothesis) edges.push({ id: 'hypothesis', from: hypothesisFactor, to: ticker,
    kind: 'hypothesis', source: 'User exploration',
    note: `Research question only: could ${nodeLabel(hypothesisFactor)} help explain ${shortTicker(ticker)}? No coefficient, evidence, or verified pathway is supplied.`,
  });
  const factors = FACTORS.filter(factor => edges.some(edge => edge.from === factor || edge.to === factor));
  return { edges, factors, hasBridge: bridges.length > 0 };
}

export function renderNetwork(host, list, network, ticker, selected, onSelect) {
  const kindLabel = TICKER_INFO[ticker]?.kind === 'stock' ? 'the company' : 'the fund';
  const OIL = [120, 210], ETF = [680, 210];
  const positions = { oil: OIL, [ticker]: ETF };
  const yPositions = { 1: [210], 2: [140, 280], 3: [112, 210, 308], 4: [92, 172, 252, 332], 5: [80, 144, 208, 272, 336] };
  network.factors.forEach((factor, i) => { positions[factor] = [400, yPositions[network.factors.length][i]]; });
  const edgeMarkup = network.edges.map((edge, index) => {
    const [x1, y1] = positions[edge.from];
    const [x2, y2] = positions[edge.to];
    let path, lx, ly;
    if (edge.from === 'oil' && edge.to === ticker) {
      const cited = edge.kind === 'cited';
      const citedIndex = network.edges.slice(0, index).filter(item => item.kind === 'cited').length;
      const arc = cited ? 400 + (citedIndex % 3) * 16 : -4;
      path = `M ${x1 + 34} ${y1 + (cited ? 34 : -34)} C 260 ${arc}, 540 ${arc}, ${x2 - 50} ${y2 + (cited ? 50 : -50)}`;
      lx = 400; ly = cited ? 376 + (citedIndex % 3) * 13 : 44;
    } else {
      const start = x1 + (edge.from === 'oil' ? 50 : 80);
      const end = x2 - (edge.to === ticker ? 72 : 80);
      path = `M ${start} ${y1} C ${(start + end) / 2} ${y1}, ${(start + end) / 2} ${y2}, ${end} ${y2}`;
      lx = (start + end) / 2; ly = (y1 + y2) / 2 - 9;
    }
    const label = edge.kind === 'hypothesis' ? 'untested' : edge.kind === 'cited' ? 'document' : `β ${number(edge.beta, 3, true)}`;
    const accessible = `${nodeLabel(edge.from)} to ${nodeLabel(edge.to)}, ${edge.kind}, ${label}`;
    const draw = edge.kind === 'measured' ? ` pathLength="1" style="--d:${index * 90}ms"` : '';
    return `<g class="edge ${edge.kind}" data-edge-index="${index}" role="button" tabindex="0" aria-label="${esc(accessible)}" aria-pressed="${edge.id === selected}"><path class="edge-hit" d="${path}"/><path class="line"${draw} d="${path}"/><text x="${lx}" y="${ly}" text-anchor="middle">${esc(label)}</text></g>`;
  }).join('');
  const factorMarkup = network.factors.map(factor => {
    const [x, y] = positions[factor];
    const label = factor === 'breakeven' ? 'US breakeven inflation' : nodeLabel(factor);
    return `<g class="node factor"><rect x="${x - 80}" y="${y - 22}" width="160" height="44" rx="22"/><text x="${x}" y="${y + 4.5}" text-anchor="middle">${esc(label)}</text></g>`;
  }).join('');
  const [ox, oy] = OIL, [ex, ey] = ETF;
  host.innerHTML = `<svg viewBox="0 0 800 430" role="group" aria-label="Exposure network for ${esc(ticker)}. Focus a line and press Enter to inspect it.">
    <text class="col-label" x="${ox}" y="26" text-anchor="middle">the shock</text>
    ${network.factors.length ? '<text class="col-label" x="400" y="26" text-anchor="middle">macro channels</text>' : ''}
    <text class="col-label" x="${ex}" y="26" text-anchor="middle">${kindLabel}</text>
    ${edgeMarkup}${factorMarkup}
    <g class="node oil" aria-hidden="true">
      <circle class="ring" cx="${ox}" cy="${oy}" r="46"/><circle class="ring" cx="${ox}" cy="${oy}" r="46"/><circle class="ring" cx="${ox}" cy="${oy}" r="46"/>
      <circle class="core" cx="${ox}" cy="${oy}" r="46"/>
      <text x="${ox}" y="${oy + 1}" text-anchor="middle">Brent</text>
      <text class="sub" x="${ox}" y="${oy + 18}" text-anchor="middle">crude · USD</text>
    </g>
    <g class="node etf">
      <rect x="${ex - 70}" y="${ey - 50}" width="140" height="100" rx="6"/>
      <text class="symbol" x="${ex}" y="${ey + 6}" text-anchor="middle">${esc(shortTicker(ticker))}</text>
      <text class="sub" x="${ex}" y="${ey + 30}" text-anchor="middle">returns in CAD</text>
    </g>
  </svg>`;
  const sync = edge => {
    host.querySelectorAll('[data-edge-index]').forEach(item => item.setAttribute('aria-pressed', String(network.edges[Number(item.dataset.edgeIndex)].id === edge.id)));
    list.querySelectorAll('[data-edge-index]').forEach(item => item.setAttribute('aria-pressed', String(network.edges[Number(item.dataset.edgeIndex)].id === edge.id)));
    onSelect(edge);
  };
  host.querySelectorAll('[data-edge-index]').forEach(element => {
    element.addEventListener('click', () => sync(network.edges[Number(element.dataset.edgeIndex)]));
    element.addEventListener('keydown', event => {
      if (['Enter', ' '].includes(event.key)) { event.preventDefault(); sync(network.edges[Number(element.dataset.edgeIndex)]); }
    });
  });
  list.innerHTML = network.edges.map((edge, i) => `<button type="button" class="pill-button" data-edge-index="${i}" aria-pressed="${edge.id === selected}">${esc(nodeLabel(edge.from))} → ${esc(nodeLabel(edge.to))} · ${edge.kind}</button>`).join('');
  list.querySelectorAll('button').forEach(button => button.addEventListener('click', () => sync(network.edges[Number(button.dataset.edgeIndex)])));
}
