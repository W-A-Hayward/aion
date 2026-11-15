export const finite = value => typeof value === 'number' && Number.isFinite(value);
export const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
})[character]);
export function number(value, digits = 3, signed = false) {
  if (!finite(value)) return 'Unavailable';
  return new Intl.NumberFormat('en-CA', {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
    signDisplay: signed ? 'exceptZero' : 'auto',
  }).format(value);
}
export const percent = (value, digits = 2) => finite(value) ? `${number(value, digits, true)}%` : 'Unavailable';
export const interval = (lo, hi, suffix = '') => finite(lo) && finite(hi)
  ? `${number(lo, 3, true)}${suffix} to ${number(hi, 3, true)}${suffix}` : 'Unavailable';
export function probability(value) {
  if (!finite(value)) return 'Unavailable';
  return value < 0.001 ? '< 0.001' : number(value);
}
export function sourceURL(value) {
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}
export const shortTicker = value => String(value).replace('.TO', '');
export const nodeLabel = value => ({
  oil: 'Brent crude', us10y: 'US 10Y yield', ca10y: 'Canada 10Y yield', ca2y: 'Canada 2Y yield',
  usdcad: 'USD / CAD', breakeven: 'US inflation expectations',
})[value] || shortTicker(value);
export function hasEstimate(row) {
  return row && [row.beta_simple, row.lo_simple, row.hi_simple, row.n_weeks].every(finite)
    && row.n_weeks > 0 && row.lo_simple <= row.beta_simple && row.beta_simple <= row.hi_simple;
}
export function signalSummary(row) {
  if (!hasEstimate(row)) return 'The estimate is unavailable.';
  if (row.lo_simple <= 0 && row.hi_simple >= 0) return 'A signal too uncertain to call.';
  return row.beta_simple < 0 ? 'An inverse relationship worth investigating.' : 'A positive relationship worth investigating.';
}
