import { config } from './config.js';
import { sourceURL } from './formatters.js';

// Statistics come only from the backend: GET {investigationUrl}?ticker=XIU.TO (lambdas/research). There is no
// local copy. Table names come from docs/data_contract.md; only sensitivities is required.
export const TABLES = Object.freeze(['sensitivities', 'links', 'chain_reconciliation',
  'scenarios', 'evidence', 'confidence', 'edges', 'rolling', 'duration_check',
  'persona_holdings', 'portfolio_exposure', 'portfolio_beta', 'alternatives']);

export function normalizeTables(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('The data response is not a table envelope.');
  if (!Array.isArray(payload.sensitivities)) throw new Error('The response must include a sensitivities array.');
  return Object.fromEntries(TABLES.map(name => {
    if (payload[name] !== undefined && !Array.isArray(payload[name])) throw new Error(`Invalid ${name} table.`);
    const rows = payload[name] ?? [];
    if (rows.some(row => !row || typeof row !== 'object' || Array.isArray(row))) throw new Error(`Invalid row in ${name}.`);
    return [name, rows];
  }));
}

export class StatisticsError extends Error {
  constructor(message, status = null) { super(message); this.name = 'StatisticsError'; this.status = status; }
}

export const statisticsConfigured = (settings = config) => Boolean(settings.investigationUrl);

/** Tables for one ticker from the research API, plus its meta (as-of week, tables that could not be read). */
export async function loadInvestigation({ ticker, signal, settings = config, transport = globalThis.fetch }) {
  if (!statisticsConfigured(settings)) throw new StatisticsError('The statistics API is not configured: set investigationUrl in config.js.');
  const url = new URL(settings.investigationUrl, globalThis.location?.href);
  if (!sourceURL(url.href)) throw new StatisticsError('The statistics API must use HTTPS.');
  url.searchParams.set('ticker', ticker);
  const timeout = AbortSignal.timeout(settings.timeoutMs ?? 15000);
  let response;
  try {
    // A simple GET (no custom or cache headers), so browsers send it without a CORS preflight.
    response = await transport(url, { credentials: 'omit', headers: { Accept: 'application/json' },
      signal: signal ? AbortSignal.any([signal, timeout]) : timeout });
  } catch (error) {
    if (error.name === 'AbortError' && signal?.aborted) throw error;
    throw new StatisticsError('Couldn’t reach the statistics API. It may not be deployed yet, or it does not allow this site (CORS). Check your connection and try again.');
  }
  const body = await response.json().catch(() => null);
  if (response.status === 404 && !body?.error) throw new StatisticsError('The statistics API is not deployed yet (GET /research returned 404).', 404);
  if (!response.ok) throw new StatisticsError(body?.error ? `The statistics API answered: ${body.error}.` : `The statistics request failed (HTTP ${response.status}).`, response.status);
  const tables = normalizeTables(body);
  const meta = body.meta && typeof body.meta === 'object' ? body.meta : {};
  return { tables, meta };
}

// All tickers in one request (GET ?ticker=ALL), kept for the session so switching tickers never reloads.
export const STATS_CACHE_KEY = 'aion.stats.v1';
const STATS_TTL_MS = 10 * 60 * 1000;
let statsMemory = null, statsInflight = null;
export async function loadAllStatistics({ signal, force = false, settings = config, transport = globalThis.fetch, storage = globalThis.sessionStorage, now = Date.now } = {}) {
  const fresh = entry => entry && now() - entry.at < STATS_TTL_MS;
  if (!force && fresh(statsMemory)) return statsMemory.data;
  if (!force) {
    try {
      const saved = JSON.parse(storage?.getItem(STATS_CACHE_KEY) ?? 'null');
      if (fresh(saved)) { statsMemory = { at: saved.at, data: { tables: normalizeTables(saved.body), meta: saved.body.meta ?? {} } }; return statsMemory.data; }
    } catch {}
  }
  if (!force && statsInflight) return statsInflight;
  statsInflight = loadInvestigation({ ticker: 'ALL', signal, settings, transport }).then(data => {
    const at = now();
    statsMemory = { at, data };
    try { storage?.setItem(STATS_CACHE_KEY, JSON.stringify({ at, body: { ...data.tables, meta: data.meta } })); } catch {}
    return data;
  }).finally(() => { statsInflight = null; });
  return statsInflight;
}

// Prefer one request for every ticker; a backend that does not know ticker=ALL yet (HTTP 400) is used one
// ticker at a time instead, each kept for the session, so a ticker is never fetched twice.
const perTicker = new Map();
let allSupported = true;
export async function loadStatistics(ticker, { signal, force = false, ...rest } = {}) {
  if (allSupported) {
    try { return await loadAllStatistics({ signal, force, ...rest }); }
    catch (error) { if (error.status !== 400) throw error; allSupported = false; }
  }
  if (!force && perTicker.has(ticker)) return perTicker.get(ticker);
  const request = loadInvestigation({ ticker, signal, ...rest }).catch(error => { perTicker.delete(ticker); throw error; });
  perTicker.set(ticker, request);
  return request;
}
export const resetStatisticsCache = () => { perTicker.clear(); allSupported = true; };
