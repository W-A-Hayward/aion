import { config } from './config.js';
import { sourceURL } from './formatters.js';

// Table names come from docs/data_contract.md. Only sensitivities is required.
export const TABLES = Object.freeze(['sensitivities', 'links', 'chain_reconciliation',
  'scenarios', 'evidence', 'confidence', 'edges', 'rolling', 'duration_check',
  'persona_holdings', 'portfolio_exposure', 'portfolio_beta', 'alternatives']);

// These are presentation provenance labels, not additional financial data fields.
export const PREVIEW_PROVENANCE = Object.freeze({
  label: 'Local preview',
  description: 'Unverified saved notebook statistics. Ticker scenarios computed locally. ZST’s updated 2Y pathway awaits fresh outputs. No live AWS connection.',
  coverage: '19 Nov 2021 — 13 Nov 2026',
  verified: 'Not verified',
  origin: 'Saved outputs · compute/run_stats.ipynb',
});
const API_PROVENANCE = Object.freeze({
  label: 'Backend response', description: 'Received from the configured API. AWS provenance is not independently verified.',
  coverage: 'Not supplied by current contract', verified: 'Not supplied', origin: 'Configured backend · table response',
});

export function normalizeTables(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('The data response is not a table envelope.');
  // Never silently replace malformed/missing required data with preview data.
  if (!Array.isArray(payload.sensitivities)) throw new Error('The response must include a sensitivities array.');
  return Object.fromEntries(TABLES.map(name => {
    if (payload[name] !== undefined && !Array.isArray(payload[name])) throw new Error(`Invalid ${name} table.`);
    const rows = payload[name] ?? [];
    if (rows.some(row => !row || typeof row !== 'object' || Array.isArray(row))) throw new Error(`Invalid row in ${name}.`);
    return [name, rows];
  }));
}

async function request(url, options = {}, signal) {
  const timeout = AbortSignal.timeout(config.timeoutMs);
  const response = await fetch(url, { ...options, credentials: 'same-origin',
    headers: { Accept: 'application/json', ...options.headers },
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
  });
  if (!response.ok) throw new Error(`The data request failed (HTTP ${response.status}).`);
  return response.json();
}

function endpoint(value) {
  if (!value) throw new Error('No backend endpoint is configured. Use Local preview to explore the saved research.');
  const url = new URL(value, globalThis.location?.href);
  if (!sourceURL(url.href)) throw new Error('The backend endpoint must use HTTP or HTTPS.');
  return url;
}

export async function loadInvestigation({ ticker, mode = 'preview', signal }) {
  const url = mode === 'preview' ? new URL('./preview-data.json', import.meta.url) : endpoint(config.investigationUrl);
  if (mode !== 'preview') url.searchParams.set('ticker', ticker);
  const tables = normalizeTables(await request(url, {}, signal));
  return { tables, provenance: mode === 'preview' ? PREVIEW_PROVENANCE : API_PROVENANCE };
}

// The workspace always reads the local snapshot: persona tables have no backend endpoint yet.
export async function loadSnapshot({ signal } = {}) {
  return normalizeTables(await request(new URL('./preview-data.json', import.meta.url), {}, signal));
}
