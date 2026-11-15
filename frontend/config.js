// No credentials. Kept unconfigured by request; repository code is not deployment proof.
// submit/status match lambdas/submit and lambdas/status. The table endpoint is still proposed.
export const config = Object.freeze({
  investigationUrl: null,
  submitUrl: null,
  statusUrl: null, // Full URL template containing {id}; use the deployed route, not a guessed one.
  timeoutMs: 15000,
  pollIntervalMs: 1200,
  jobTimeoutMs: 120000,
});

// The data contract's 14 MVP ("core") tickers, in contract order (docs/data_contract.md,
// compute/stats.py CORE_TICKERS). This is the only list users can research, watch,
// save, or put in a mock portfolio. Personas and alternatives use only these tickers.
export const CORE_TICKERS = Object.freeze([
  'XIU.TO', 'ENB.TO', 'XOM', 'TLT', 'XBB.TO', 'ZST.TO', 'QQQ',
  'SHOP.TO', 'SPY', 'VFV.TO', 'XSP.TO', 'XESG.TO', 'ATD.TO', 'RY.TO',
]);

// Presentation labels only, not financial data. kind drives wording (fund vs company).
export const TICKER_INFO = Object.freeze({
  'XIU.TO': { name: 'iShares S&P/TSX 60', blurb: 'Canadian large-cap equity', kind: 'etf' },
  'ENB.TO': { name: 'Enbridge', blurb: 'Pipelines and energy infrastructure', kind: 'stock' },
  XOM: { name: 'Exxon Mobil', blurb: 'Integrated oil and gas', kind: 'stock' },
  TLT: { name: 'iShares 20+ Year Treasury', blurb: 'Long-term US Treasury bonds', kind: 'etf' },
  'XBB.TO': { name: 'iShares Core Canadian Universe Bond', blurb: 'Canadian bonds', kind: 'etf' },
  'ZST.TO': { name: 'BMO Ultra Short-Term Bond', blurb: 'Ultra short-term bonds', kind: 'etf' },
  QQQ: { name: 'Invesco QQQ', blurb: 'Nasdaq-100, US tech-heavy equity', kind: 'etf' },
  'SHOP.TO': { name: 'Shopify', blurb: 'E-commerce software', kind: 'stock' },
  SPY: { name: 'SPDR S&P 500', blurb: 'US large-cap equity', kind: 'etf' },
  'VFV.TO': { name: 'Vanguard S&P 500 Index', blurb: 'S&P 500, Canadian-listed', kind: 'etf' },
  'XSP.TO': { name: 'iShares Core S&P 500 (CAD-hedged)', blurb: 'S&P 500, CAD-hedged', kind: 'etf' },
  'XESG.TO': { name: 'iShares ESG Aware MSCI Canada', blurb: 'Canadian ESG equity', kind: 'etf' },
  'ATD.TO': { name: 'Alimentation Couche-Tard', blurb: 'Convenience stores and fuel', kind: 'stock' },
  'RY.TO': { name: 'Royal Bank of Canada', blurb: 'Canadian bank', kind: 'stock' },
});

export const ETF_TICKERS = Object.freeze(CORE_TICKERS.filter(t => TICKER_INFO[t].kind === 'etf'));
export const STOCK_TICKERS = Object.freeze(CORE_TICKERS.filter(t => TICKER_INFO[t].kind === 'stock'));
export const isSupported = ticker => CORE_TICKERS.includes(ticker);
export const SHOCKS = Object.freeze([-30, -15, 15, 30]);
