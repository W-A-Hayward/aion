// Fuel card: Statistics Canada monthly regular-gasoline price (fuel-series.json, built by
// build-fuel-series.py from library source SRC-037). The headline is the highest month in the
// selected window; the hover readout shows the exact monthly value. Nothing is smoothed or filled.
import { createPeakChart } from './peak-chart.js';

const host = document.querySelector('#fuel-card');
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const label = ym => `${MONTHS[Number(ym.slice(5, 7)) - 1]} ${ym.slice(0, 4)}`;
const WINDOWS = { 'Beta sample': '2021-11', '10 years': '2016-10', 'Since 2006': '0000' };

function slice(series, period) {
  const from = WINDOWS[period];
  const idx = series.months.map((m, i) => (m >= from ? i : -1)).filter(i => i >= 0);
  const data = idx.map(i => series.values[i]), labels = idx.map(i => label(series.months[i]));
  const peak = data.indexOf(Math.max(...data));
  return { data, labels, peak, peakLabel: labels[peak], value: data[peak] };
}

function widthFor() {
  const w = host.parentElement.clientWidth;
  return Math.round(Math.max(260, Math.min(400, w)));
}

async function init() {
  if (!host) return;
  let series;
  try {
    series = await (await fetch('./fuel-series.json')).json();
    if (!series.months?.length) throw new Error('empty');
  } catch {
    host.closest('.fuel-band')?.setAttribute('hidden', '');
    return;
  }
  const last = series.months.length - 1;
  const latest = `${series.values[last].toFixed(1)}¢ in ${label(series.months[last])}`;
  const fill = (sel, text) => document.querySelectorAll(sel).forEach(n => { n.textContent = text; });

  let period = 'Beta sample';
  const view = () => {
    const s = slice(series, period);
    fill('[data-fuel-peak]', `${s.value.toFixed(1)}¢`);
    fill('[data-fuel-peak-month]', s.peakLabel);
    fill('[data-fuel-latest]', latest);
    return {
      data: s.data, labels: s.labels, value: s.value, period,
      caption: `Peak month: ${s.peakLabel} · latest ${latest}`,
      ariaLabel: `Monthly average price of regular gasoline in Canada, ${s.labels[0]} to ${s.labels.at(-1)}. Highest: ${s.value.toFixed(1)} cents per litre in ${s.peakLabel}. Latest: ${latest}.`,
    };
  };
  const card = createPeakChart(host, {
    ...view(),
    width: widthFor(),
    valueSuffix: '¢/L',
    decimals: 1,
    title: 'Regular gasoline · Canada · highest month',
    updatedText: `StatCan · to ${label(series.months[last])}`,
    periods: Object.keys(WINDOWS),
    accent: '#16849a',
    formatValue: v => `${v.toFixed(1)}¢`,
    onPeriodChange: p => { period = p; card.update(view()); },
  });
  let timer;
  new ResizeObserver(() => { clearTimeout(timer); timer = setTimeout(() => card.resize(widthFor()), 60); }).observe(host.parentElement);
}
init();
