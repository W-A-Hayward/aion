import { CORE_TICKERS, SHOCKS, isSupported } from './config.js';
import { finite } from './formatters.js';

export { CORE_TICKERS };

// Fictional demo investors from docs/data_contract.md ("Personas"). Weights live in the
// persona_holdings table; these are presentation details only.
export const PERSONAS = Object.freeze({
  robert: { name: 'Robert', initials: 'RO', title: 'Income & stability', description: 'A bond-heavy sample with Canadian bank and pipeline exposure.', risk: 'Low–moderate', horizon: '3–5 years', experience: 'Advanced' },
  amira: { name: 'Amira', initials: 'AM', title: 'Long-term growth', description: 'A sample tilted toward US tech and Canadian e-commerce.', risk: 'High', horizon: '15+ years', experience: 'Intermediate' },
  mateo: { name: 'Mateo', initials: 'MA', title: 'Broad equity, ESG-minded', description: 'A two-fund sample with a stated ESG preference.', risk: 'Moderate', horizon: '8–12 years', experience: 'Intermediate' },
});
// Sample weights: compute/stats.py PERSONAS (docs/data_contract.md persona_holdings). Kept here so the app needs no
// local statistics file to show a sample portfolio.
export const PERSONA_HOLDINGS = Object.freeze({
  robert: Object.freeze([{ ticker: 'XBB.TO', weight: 0.4 }, { ticker: 'TLT', weight: 0.3 }, { ticker: 'ENB.TO', weight: 0.15 }, { ticker: 'RY.TO', weight: 0.15 }]),
  amira: Object.freeze([{ ticker: 'QQQ', weight: 0.5 }, { ticker: 'SHOP.TO', weight: 0.25 }, { ticker: 'XIU.TO', weight: 0.25 }]),
  mateo: Object.freeze([{ ticker: 'XIU.TO', weight: 0.5 }, { ticker: 'VFV.TO', weight: 0.5 }]),
});
export const MAX_PORTFOLIOS = 20;
export const STORAGE_KEY = 'cascade.workspace.v1';
export const DEFAULT_NAME = 'Your workspace';
export const MAX_SAVED = 50;
export const defaults = () => ({
  version: 1,
  profile: { name: DEFAULT_NAME, goal: 'Understand what moves my portfolio', experience: 'beginner' },
  portfolio: 'robert', capital: 10000, custom: null, watchlist: ['XIU.TO', 'TLT'], saved: [], portfolios: [],
});
const text = (value, max, fallback = '') => typeof value === 'string' ? value.trim().slice(0, max) : fallback;

export function validateHoldings(holdings) {
  if (!Array.isArray(holdings) || !holdings.length || holdings.length > CORE_TICKERS.length) return `Add between 1 and ${CORE_TICKERS.length} holdings.`;
  const unsupported = holdings.find(row => !row || !isSupported(row.ticker));
  if (unsupported) return `${unsupported?.ticker || 'That ticker'} isn’t supported. Choose from the ${CORE_TICKERS.length} tickers in the list.`;
  if (new Set(holdings.map(row => row.ticker)).size !== holdings.length) return 'Each ticker can appear only once.';
  if (holdings.some(row => !finite(row.weight) || row.weight <= 0 || row.weight > 1)) return 'Each weight must be more than 0% and at most 100%.';
  const total = holdings.reduce((sum, row) => sum + row.weight, 0);
  if (Math.abs(total - 1) > 0.000001) return `Weights must add up to 100%. They add up to ${(total * 100).toFixed(2)}%.`;
  return null;
}

// Equal weights in 0.01% steps that sum to exactly 100% (e.g. 33.34 / 33.33 / 33.33).
export function splitEvenly(count) {
  if (!Number.isInteger(count) || count < 1) return [];
  const base = Math.floor(10000 / count), extra = 10000 - base * count;
  return Array.from({ length: count }, (_, i) => (base + (i < extra ? 1 : 0)) / 10000);
}

export function sanitizeWorkspace(input) {
  const data = defaults();
  if (!input || input.version !== 1) return data;
  data.profile = {
    name: text(input.profile?.name, 60, data.profile.name) || data.profile.name,
    goal: text(input.profile?.goal, 140, data.profile.goal) || data.profile.goal,
    experience: input.profile?.experience === 'expert' ? 'expert' : 'beginner',
  };
  if (finite(input.capital) && input.capital > 0 && input.capital <= 100000000) data.capital = input.capital;
  if (input.custom && !validateHoldings(input.custom.holdings)) {
    data.custom = { name: text(input.custom.name, 60, 'My mock portfolio') || 'My mock portfolio',
      holdings: input.custom.holdings.map(({ ticker, weight }) => ({ ticker, weight })) };
  }
  data.portfolio = Object.hasOwn(PERSONAS, input.portfolio) ? input.portfolio : input.portfolio === 'custom' && data.custom ? 'custom' : 'robert';
  // Saved portfolios: named mixes the user can switch back to (shown under My portfolio).
  if (Array.isArray(input.portfolios)) data.portfolios = input.portfolios
    .filter(item => item && typeof item.id === 'string' && !validateHoldings(item.holdings) && Number.isFinite(Date.parse(item.savedAt)))
    .slice(0, MAX_PORTFOLIOS).map(item => ({ id: text(item.id, 80), name: text(item.name, 60, 'Saved portfolio') || 'Saved portfolio',
      holdings: item.holdings.map(({ ticker, weight }) => ({ ticker, weight })), savedAt: item.savedAt,
      capital: finite(item.capital) && item.capital > 0 ? item.capital : null }));
  if (Array.isArray(input.watchlist)) data.watchlist = [...new Set(input.watchlist.filter(isSupported))];
  if (Array.isArray(input.saved)) data.saved = input.saved.filter(item => item && isSupported(item.ticker) && SHOCKS.includes(item.shock)
    && ['preview', 'api'].includes(item.source) && typeof item.id === 'string' && Number.isFinite(Date.parse(item.savedAt))).slice(0, MAX_SAVED).map(item => ({
    id: text(item.id, 80), ticker: item.ticker, shock: item.shock, source: item.source,
    mode: item.mode === 'expert' ? 'expert' : 'beginner', title: text(item.title, 80, 'Saved investigation') || 'Saved investigation',
    note: text(item.note, 2000), savedAt: item.savedAt,
    beta: finite(item.beta) ? item.beta : null, lo: finite(item.lo) ? item.lo : null, hi: finite(item.hi) ? item.hi : null,
  }));
  return data;
}

// Parses an exported workspace file. Returns { workspace } or { error }; never throws.
export function parseImport(raw) {
  let input;
  try { input = JSON.parse(raw); } catch { return { error: 'That file isn’t valid JSON. Choose a file exported from Cascade.' }; }
  if (!input || input.version !== 1 || typeof input.profile !== 'object') return { error: 'That file isn’t a Cascade workspace export.' };
  const workspace = sanitizeWorkspace(input);
  const dropped = [
    Array.isArray(input.watchlist) && input.watchlist.length > workspace.watchlist.length,
    Array.isArray(input.saved) && input.saved.length > workspace.saved.length,
    Boolean(input.custom) && !workspace.custom,
  ].some(Boolean);
  return { workspace, dropped };
}

export function createWorkspaceStore(storage) {
  let data = defaults(), persisted = true;
  try { const raw = storage?.getItem(STORAGE_KEY); if (raw) data = sanitizeWorkspace(JSON.parse(raw)); if (!storage) persisted = false; }
  catch { persisted = false; }
  const save = () => { try { if (!storage) throw Error('Storage unavailable'); storage.setItem(STORAGE_KEY, JSON.stringify(data)); persisted = true; } catch { persisted = false; } };
  return {
    get: () => structuredClone(data), isPersistent: () => persisted,
    update: updater => { const next = structuredClone(data); updater(next); data = sanitizeWorkspace(next); save(); return structuredClone(data); },
    replace: next => { data = sanitizeWorkspace(next); save(); return structuredClone(data); },
    reset: () => { data = defaults(); save(); return structuredClone(data); },
  };
}

export function portfolioRows(data, workspace) {
  if (workspace.portfolio === 'custom') return workspace.custom?.holdings ?? [];
  if (!data?.persona_holdings) return (PERSONA_HOLDINGS[workspace.portfolio] ?? []).map(h => ({ persona: workspace.portfolio, ...h }));
  return data.persona_holdings.filter(row => row.persona === workspace.portfolio);
}

// Same columns and maths as compute/stats.py portfolio_exposure().
export function contributions(data, holdings) {
  return holdings.map(row => {
    const s = data.sensitivities.find(item => item.ticker === row.ticker);
    const beta = finite(s?.beta_simple) ? s.beta_simple : null;
    return { ticker: row.ticker, weight: row.weight, beta, lo: finite(s?.lo_simple) ? s.lo_simple : null,
      hi: finite(s?.hi_simple) ? s.hi_simple : null, contribution: beta === null ? null : row.weight * beta };
  });
}

// Proxy only: alternatives() uses this sum. portfolio_beta() now regresses
// log(1 + sum(weight * (exp(asset log return) - 1))), so equality is not guaranteed.
// This approximation has no portfolio standard error or confidence interval.
export function weightedBeta(data, holdings) {
  const rows = contributions(data, holdings);
  if (!rows.length || rows.some(row => row.contribution === null)) return null;
  return rows.reduce((sum, row) => sum + row.contribution, 0);
}

// compute/stats.py shock_impact_pct().
export const shockImpact = (beta, shock) => finite(beta) && SHOCKS.includes(shock)
  ? 100 * Math.expm1(beta * Math.log1p(shock / 100)) : null;
