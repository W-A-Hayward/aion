// Peak Chart: vanilla ES-module port of "Peak Chart" by Louis Studios
// (https://studios.lou15.com, via 21st.dev). Same card geometry, painted glow field, timeline and
// interactions as the React original; React state replaced by a small controller object.
// Use: const card = createPeakChart(host, { data, labels, value, ... }); card.update({...}); card.destroy();

const CW = 540, CH = 696, CR = 56, HN = CH / CW, RN = CR / CW, BX = 0.32 * CW, BY = 0.16 * CW;
const FIELD_FILL = '#1678ff';
const FIELD_SHADES = [
  { shape: [0.4748, 0.8152, 0.7509, 0.8801, 0.7026], color: '#000000', opacity: 1 },
  { shape: [0.3741, 0.2723, 0.7371, 0.3009, 0.1168], color: '#020000', opacity: 1 },
  { shape: [0.7846, 0.0251, 0.3833, 0.1301, -0.5566], color: '#2e85ff', opacity: 0.4756 },
  { shape: [0.6206, -0.2018, 0.1282, 0.5909, 0.2754], color: '#3584ff', opacity: 0.3146 },
  { shape: [0.6, 1.2391, 0.827, 0.2111, -1.6357], color: '#000d1e', opacity: 1 },
  { shape: [0.0964, 0.5388, 1000, 0.1285, 0.5421], color: '#000005', opacity: 0.2298 },
];
const FIELD_RIMS = [
  { shape: [0.1207, -0.0365, 0.0492], color: '#2667ff', opacity: 1 },
  { shape: [0.0667, -0.0166, 0.0176], color: '#467dff', opacity: 1 },
  { shape: [0.037, -0.0134, 0.0154], color: '#c2ffff', opacity: 0.8091 },
];
const HALO = { cx: 0.4996, cy: 0.6438, sx: 0.2498, sy: 0.2433, opacity: 0.845, color: '#0e50ff' };
const BREATH_GAIN = 0.42, GRAIN = 1.7;
const PLOT_X0 = 20.29, PLOT_X1 = 503.69, PLOT_TOP = 158.49, PLOT_BOTTOM = 385.28;
const LINE_W = 7.1, LINE_COLOR = '#6496e2', LINE_FALLOFF = 108, LINE_POWER = 1.44, LINE_CENTER = 12;
const DOT_R = 13, DOT_DX = 8, DOT_DY = 2.6;
const GRID_DX = 40.64, GRID_DY = 40.07, GRID_Y0 = 468.7, GRID_COLOR = '#5a87e1', GRID_ALPHA = 0.23;
const T_GRID = 0.9, T_DRAW0 = 0.25, T_DRAW = 2.1, T_NUM0 = 1.0, T_NUM = 1.7, T_REST = 3.3, T_MORPH = 0.75;
const BASE_ACCENT = '#4f8ef7', DOT_TOP = '#2680ff', DOT_MID = '#75aafa', DOT_BOTTOM = '#d0e4fd', DOT_GLOW = '#287dff', PULSE_COLOR = '#78afff';

const clamp01 = x => (x < 0 ? 0 : x > 1 ? 1 : x);
const smooth = x => { const t = clamp01(x); return t * t * (3 - 2 * t); };
const easeInOut = x => { const t = clamp01(x); return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; };
const easeOut = x => 1 - Math.pow(1 - clamp01(x), 3);
const backOut = x => { const t = clamp01(x), c = 1.9; return 1 + (c + 1) * Math.pow(t - 1, 3) + c * Math.pow(t - 1, 2); };
function erf(x) {
  const s = x < 0 ? -1 : 1, a = Math.abs(x), t = 1 / (1 + 0.3275911 * a);
  return s * (1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-a * a));
}
const phi = x => 0.5 * (1 + erf(x / Math.SQRT2));
function sdf(u, v) {
  const qx = Math.abs(u - 0.5) - (0.5 - RN), qy = Math.abs(v - HN / 2) - (HN / 2 - RN);
  const ox = Math.max(qx, 0), oy = Math.max(qy, 0);
  return Math.sqrt(ox * ox + oy * oy) + Math.min(Math.max(qx, qy), 0) - RN;
}
function rng(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function rgbOf(color) {
  const h = /^#([0-9a-f]{6})$/i.exec(color.trim());
  return h ? [0, 2, 4].map(i => parseInt(h[1].slice(i, i + 2), 16)) : [0, 0, 0];
}
const rgba = (c, a) => `rgba(${rgbOf(c).join(',')},${a.toFixed(4)})`;
function hslOf(color) {
  const [r, g, b] = rgbOf(color).map(v => v / 255);
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, d = mx - mn;
  if (!d) return [0, 0];
  const h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [(h * 60 + 360) % 360, d / (1 - Math.abs(2 * l - 1))];
}
function makeCanvas(w, h) {
  const c = document.createElement('canvas');
  c.width = Math.max(1, Math.round(w)); c.height = Math.max(1, Math.round(h));
  return c;
}

function buildField(px, seed) {
  const w = Math.round(px), h = Math.round(px * HN);
  const rest = makeCanvas(w, h), lift = makeCanvas(w, h);
  const c1 = rest.getContext('2d'), c2 = lift.getContext('2d');
  const i1 = c1.createImageData(w, h), i2 = c2.createImageData(w, h), d1 = i1.data, d2 = i2.data;
  const rand = rng(seed), fill = rgbOf(FIELD_FILL);
  const shades = FIELD_SHADES.map(({ shape: [cx, cy, sx, sy, th], color, opacity }) =>
    ({ cx, cy, isx: 1 / Math.abs(sx), isy: 1 / Math.abs(sy), c: Math.cos(th), s: Math.sin(th), rgb: rgbOf(color), a: opacity }));
  const rims = FIELD_RIMS.map(({ shape: [off, sp, sg], color, opacity }) => ({ off, sp, sg, rgb: rgbOf(color), a: opacity }));
  const k2 = 1 + BREATH_GAIN;
  for (let j = 0; j < h; j++) {
    const v = (j + 0.5) / w;
    for (let i = 0; i < w; i++) {
      const u = (i + 0.5) / w;
      let r = fill[0], g = fill[1], b = fill[2];
      for (const o of shades) {
        const du = u - o.cx, dv = v - o.cy;
        const x = (o.c * du + o.s * dv) * o.isx, y = (-o.s * du + o.c * dv) * o.isy;
        const m = o.a * Math.exp(-0.5 * (x * x + y * y));
        r += m * (o.rgb[0] - r); g += m * (o.rgb[1] - g); b += m * (o.rgb[2] - b);
      }
      let r2 = r, g2 = g, b2 = b;
      for (const o of rims) {
        const vs = v + o.off, dx = Math.min(u, 1 - u), dy = Math.min(vs, HN - vs);
        const ratio = Math.min(1, phi((-sdf(u, vs) - o.sp) / o.sg) / Math.max(1e-9, phi((Math.min(dx, dy) - o.sp) / o.sg)));
        const m = o.a * (1 - phi((dx - o.sp) / o.sg) * phi((dy - o.sp) / o.sg) * ratio);
        r += m * (o.rgb[0] - r); g += m * (o.rgb[1] - g); b += m * (o.rgb[2] - b);
        const m2 = Math.min(1, m * k2);
        r2 += m2 * (o.rgb[0] - r2); g2 += m2 * (o.rgb[1] - g2); b2 += m2 * (o.rgb[2] - b2);
      }
      const n = (rand() + rand() + rand() - 1.5) * 2 * GRAIN, p = (j * w + i) * 4;
      d1[p] = r + n; d1[p + 1] = g + n; d1[p + 2] = b + n; d1[p + 3] = 255;
      d2[p] = r2 + n; d2[p + 1] = g2 + n; d2[p + 2] = b2 + n; d2[p + 3] = 255;
    }
  }
  c1.putImageData(i1, 0, 0); c2.putImageData(i2, 0, 0);
  return { rest, lift };
}

function buildHalo(px) {
  const s = 0.25;
  const w = Math.max(8, Math.round((CW + 2 * BX) * px * s / CW)), h = Math.max(8, Math.round((CH + 2 * BY) * px * s / CW));
  const c = makeCanvas(w, h), ctx = c.getContext('2d'), img = ctx.createImageData(w, h), [hr, hg, hb] = rgbOf(HALO.color);
  for (let j = 0; j < h; j++) {
    const v = ((j + 0.5) / h * (CH + 2 * BY) - BY) / CW;
    for (let i = 0; i < w; i++) {
      const u = ((i + 0.5) / w * (CW + 2 * BX) - BX) / CW;
      const a = (u - HALO.cx) / HALO.sx, e = (v - HALO.cy) / HALO.sy, p = (j * w + i) * 4;
      img.data[p] = hr; img.data[p + 1] = hg; img.data[p + 2] = hb;
      img.data[p + 3] = Math.min(255, Math.exp(-0.5 * (a * a + e * e)) * HALO.opacity * 255);
    }
  }
  ctx.putImageData(img, 0, 0);
  return c;
}

function buildGrid(px) {
  const w = Math.round(px), h = Math.round(px * HN), c = makeCanvas(w, h), ctx = c.getContext('2d'), s = px / CW;
  ctx.scale(s, s);
  ctx.strokeStyle = GRID_COLOR; ctx.lineWidth = 1; ctx.beginPath();
  for (let k = -6; k <= 6; k++) { const x = CW / 2 + GRID_DX * k; ctx.moveTo(x, 250); ctx.lineTo(x, CH); }
  for (let k = -6; k <= 6; k++) { const y = GRID_Y0 + GRID_DY * k; if (y < 250 || y > CH) continue; ctx.moveTo(0, y); ctx.lineTo(CW, y); }
  ctx.stroke();
  const mw = 64, mh = Math.round(64 * HN), m = makeCanvas(mw, mh), mc = m.getContext('2d'), img = mc.createImageData(mw, mh);
  for (let j = 0; j < mh; j++) {
    const my = smooth(((j + 0.5) / mh * CH - 350) / 230);
    for (let i = 0; i < mw; i++) {
      const mx = Math.exp(-0.5 * Math.pow(((i + 0.5) / mw * CW - CW / 2) / 92, 2));
      img.data[(j * mw + i) * 4 + 3] = Math.round(255 * GRID_ALPHA * mx * my);
    }
  }
  mc.putImageData(img, 0, 0);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalCompositeOperation = 'destination-in';
  ctx.drawImage(m, 0, 0, w, h);
  return c;
}

// Monotone cubic (Steffen): never overshoots, so the highest data point is the top of the curve.
function buildCurve(data) {
  const vals = data.length >= 2 ? data : data.length === 1 ? [data[0], data[0]] : [0, 0];
  const n = vals.length;
  let lo = Infinity, hi = -Infinity, pk = 0;
  vals.forEach((v, i) => { if (v < lo) lo = v; if (v > hi) { hi = v; pk = i; } });
  const span = hi - lo || 1;
  const yv = vals.map(v => (hi === lo ? (PLOT_TOP + PLOT_BOTTOM) / 2 : PLOT_TOP + (1 - (v - lo) / span) * (PLOT_BOTTOM - PLOT_TOP)));
  const h = (PLOT_X1 - PLOT_X0) / (n - 1), sl = [];
  for (let i = 0; i < n - 1; i++) sl.push((yv[i + 1] - yv[i]) / h);
  const m = [sl[0]];
  for (let i = 1; i < n - 1; i++) {
    const a = sl[i - 1], b = sl[i];
    m.push((Math.sign(a) + Math.sign(b)) * Math.min(Math.abs(a), Math.abs(b), 0.25 * Math.abs(a + b)));
  }
  m.push(sl[n - 2]);
  const ys = new Float32Array(CW + 1);
  for (let x = 0; x <= CW; x++) {
    let y;
    if (x <= PLOT_X0) y = yv[0] + (x - PLOT_X0) * m[0];
    else if (x >= PLOT_X1) y = yv[n - 1] + (x - PLOT_X1) * m[n - 1];
    else {
      const t = (x - PLOT_X0) / h, i = Math.min(n - 2, Math.floor(t)), f = t - i, f2 = f * f, f3 = f2 * f;
      y = (2 * f3 - 3 * f2 + 1) * yv[i] + (f3 - 2 * f2 + f) * h * m[i] + (-2 * f3 + 3 * f2) * yv[i + 1] + (f3 - f2) * h * m[i + 1];
    }
    ys[x] = y;
  }
  return { ys, peakX: PLOT_X0 + pk * h, lo, hi, n };
}
function curveY(ys, x) {
  const xc = Math.max(0, Math.min(CW, x)), i = Math.min(CW - 1, Math.floor(xc)), f = xc - i;
  return ys[i] * (1 - f) + ys[i + 1] * f;
}
const lineAlpha = d => Math.exp(-Math.pow(Math.abs(d) / LINE_FALLOFF, LINE_POWER));
function inverseEase(target) {
  let lo = 0, hi = 1;
  for (let i = 0; i < 24; i++) { const m = (lo + hi) / 2; if (easeInOut(m) < target) lo = m; else hi = m; }
  return (lo + hi) / 2;
}
function frameAt(t) {
  return {
    grid: smooth(t / T_GRID), draw: easeInOut((t - T_DRAW0) / T_DRAW),
    dotS: backOut((t - T_DRAW0) / 0.4), dotA: smooth((t - T_DRAW0) / 0.2),
    num: easeOut((t - T_NUM0) / T_NUM), numA: smooth((t - T_NUM0) / 0.45), numY: 1 - easeOut((t - T_NUM0) / 0.7),
    breath: t > T_REST ? 0.6 * Math.pow(Math.sin((Math.PI * (t - T_REST)) / 7), 2) : 0,
  };
}

const h = (tag, style = {}, attrs = {}) => {
  const node = document.createElement(tag);
  Object.assign(node.style, style);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
};

export function createPeakChart(host, opts) {
  const o = {
    value: 0, valueSuffix: '', decimals: 0, title: '', caption: '', updatedText: '', periods: [], period: '',
    onPeriodChange: null, accent: BASE_ACCENT, width: 420, formatValue: null, labels: null, ariaLabel: '',
    font: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    ...opts,
  };
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const L = { curve: buildCurve(o.data), from: null, morph: 1, value: o.value, shownValue: 0, valueFrom: 0, valueT: 1,
    hover: null, hoverX: 0, hoverMix: 0 };
  let raf = 0, io = null, onVis = null, clock = reduce ? T_REST + 0.01 : 0, started = reduce, visible = true, last = 0;
  let menuOpen = false;
  const nodes = {};

  function tint() {
    const a = hslOf(o.accent), b = hslOf(BASE_ACCENT);
    let d = a[0] - b[0];
    if (d > 180) d -= 360; if (d < -180) d += 360;
    const k = b[1] > 0 ? a[1] / b[1] : 1;
    return Math.abs(d) < 0.5 && Math.abs(k - 1) < 0.02 ? '' : `hue-rotate(${d.toFixed(1)}deg) saturate(${k.toFixed(3)})`;
  }
  const digits = v => v.toLocaleString('en-CA', { minimumFractionDigits: o.decimals, maximumFractionDigits: o.decimals });

  function mount() {
    const u = o.width / CW, px = n => `${(n * u).toFixed(3)}px`;
    const text = { position: 'absolute', whiteSpace: 'nowrap', fontFamily: o.font, fontStretch: '110%', fontWeight: 300, margin: 0, lineHeight: 1 };
    const card = h('div', { position: 'relative', width: `${o.width}px`, height: `${o.width * HN}px`, borderRadius: px(CR), flex: 'none',
      fontFamily: o.font, color: '#fff', userSelect: 'none', webkitUserSelect: 'none' }, { 'data-peak-chart': '', role: 'img', 'aria-label': o.ariaLabel });
    const canvas = h('canvas', { position: 'absolute', left: 0, top: 0, pointerEvents: 'none', filter: tint() }, { 'aria-hidden': 'true' });
    const surface = h('div', { position: 'absolute', left: 0, top: px(96), width: '100%', height: px(330), touchAction: 'pan-y', cursor: 'crosshair' });
    const updated = h('p', { ...text, left: px(45.6), top: px(43.6), fontSize: px(18.6), fontWeight: 200, color: '#a7a299' });
    updated.textContent = o.updatedText;
    const pill = h('button', { position: 'absolute', right: px(46), top: px(35), height: px(37), borderRadius: px(18.5), border: 0,
      padding: `0 ${px(19.8)} 0 ${px(19.4)}`, display: o.periods.length ? 'flex' : 'none', alignItems: 'center', gap: px(6.72),
      background: 'rgba(255,255,255,0.13)', cursor: 'pointer', color: '#f2dcc0', fontFamily: o.font, fontSize: px(17.2), fontWeight: 300 },
      { type: 'button', 'aria-haspopup': 'listbox', 'aria-expanded': 'false', 'aria-label': 'Period' });
    const pillText = h('span'); pillText.textContent = o.period;
    pill.append(pillText);
    pill.insertAdjacentHTML('beforeend', `<svg viewBox="0 0 12 7" aria-hidden="true" style="width:${px(12)};height:${px(7)};overflow:visible;transition:transform .2s"><path d="M.8.8 6 6 11.2.8" fill="none" stroke="currentColor" stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/></svg>`);
    const menu = h('div', { position: 'absolute', right: px(46), top: px(80), minWidth: px(170), padding: px(6), borderRadius: px(16), zIndex: 3,
      background: 'rgba(40,26,10,0.72)', border: '1px solid rgba(255,255,255,0.12)', boxShadow: '0 18px 40px -12px rgba(0,0,0,0.6)',
      backdropFilter: 'blur(18px)', webkitBackdropFilter: 'blur(18px)', transformOrigin: 'top right',
      transition: 'opacity .18s ease, transform .22s cubic-bezier(.2,.9,.3,1.2), visibility .22s', opacity: 0, visibility: 'hidden',
      transform: `translateY(${px(-6)}) scale(0.96)` }, { role: 'listbox', 'aria-label': 'Period' });
    const read = h('div', { position: 'absolute', left: 0, top: 0, opacity: 0, pointerEvents: 'none', zIndex: 2, display: 'flex', alignItems: 'baseline',
      gap: px(7), padding: `${px(7)} ${px(11)}`, borderRadius: px(11), background: 'rgba(48,30,8,0.6)', border: '1px solid rgba(255,210,160,0.2)',
      backdropFilter: 'blur(10px)', webkitBackdropFilter: 'blur(10px)', whiteSpace: 'nowrap', fontFamily: o.font }, { 'aria-hidden': 'true' });
    const readVal = h('span', { fontSize: px(16), fontWeight: 600, color: '#fff' }), readLab = h('span', { fontSize: px(12.5), color: '#d6c2a8' });
    read.append(readVal, readLab);
    const title = h('p', { ...text, left: 0, right: 0, textAlign: 'center', top: px(441.4), fontSize: px(20.2), fontWeight: 200, color: '#b0a89b' });
    const num = h('div', { position: 'absolute', left: 0, right: 0, top: px(469), display: 'flex', justifyContent: 'center', opacity: 0 });
    const value = h('div', { position: 'relative', fontWeight: 500, fontSize: px(89.2), lineHeight: 1, letterSpacing: px(-0.5), whiteSpace: 'nowrap' });
    const box = h('span', { position: 'relative', display: 'inline-block', fontVariantNumeric: 'tabular-nums' });
    const ghost = h('span', { visibility: 'hidden' }), dig = h('span', { position: 'absolute', right: 0, top: 0 });
    const suffix = h('span', { display: 'inline-block', fontSize: '0.42em', marginLeft: px(6), color: '#d9cbb8', fontWeight: 400 });
    box.append(ghost, dig); value.append(box, suffix); num.append(value);
    const caption = h('p', { ...text, left: 0, right: 0, textAlign: 'center', top: px(576), fontSize: px(13.2), fontWeight: 300, color: '#b0a89b' });
    card.append(canvas, surface, updated, pill, menu, read, title, num, caption);
    host.replaceChildren(card);
    Object.assign(nodes, { card, canvas, surface, pill, pillText, menu, read, readVal, readLab, title, num, ghost, dig, suffix, caption, u });
    paintText();
    renderMenu();

    surface.addEventListener('pointermove', onMove);
    surface.addEventListener('pointerdown', onMove);
    surface.addEventListener('pointerleave', onLeave);
    surface.addEventListener('pointercancel', onLeave);
    pill.addEventListener('click', () => setMenu(!menuOpen));
    startLoop();
  }

  function paintText() {
    nodes.title.textContent = o.title;
    nodes.caption.textContent = o.caption;
    nodes.ghost.textContent = digits(o.value);
    nodes.suffix.textContent = o.valueSuffix;
    nodes.pillText.textContent = o.period;
    nodes.card.setAttribute('aria-label', o.ariaLabel);
  }
  function renderMenu() {
    const px = n => `${(n * nodes.u).toFixed(3)}px`;
    nodes.menu.replaceChildren(...o.periods.map(p => {
      const b = h('button', { display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', height: px(36), padding: `0 ${px(12)}`,
        border: 0, borderRadius: px(10), background: p === o.period ? 'rgba(255,255,255,0.1)' : 'transparent', cursor: 'pointer',
        color: p === o.period ? '#fff3e2' : '#d8c7b0', fontFamily: o.font, fontSize: px(15.5), textAlign: 'left' },
        { type: 'button', role: 'option', 'aria-selected': String(p === o.period) });
      b.textContent = p;
      b.addEventListener('click', () => { setMenu(false); if (p !== o.period) o.onPeriodChange?.(p); });
      return b;
    }));
  }
  function setMenu(open) {
    menuOpen = open;
    const px = n => `${(n * nodes.u).toFixed(3)}px`;
    Object.assign(nodes.menu.style, open ? { opacity: 1, visibility: 'visible', transform: 'none' }
      : { opacity: 0, visibility: 'hidden', transform: `translateY(${px(-6)}) scale(0.96)` });
    nodes.pill.setAttribute('aria-expanded', String(open));
    nodes.pill.querySelector('svg').style.transform = open ? 'rotate(180deg)' : 'none';
    if (open) nodes.menu.querySelector('[aria-selected=true]')?.focus();
  }
  const outside = e => { if (menuOpen && !nodes.menu.contains(e.target) && !nodes.pill.contains(e.target)) setMenu(false); };
  const esc = e => { if (menuOpen && e.key === 'Escape') { setMenu(false); nodes.pill.focus(); } };
  addEventListener('pointerdown', outside);
  addEventListener('keydown', esc);

  function onMove(e) {
    const r = nodes.card.getBoundingClientRect();
    const nx = Math.max(PLOT_X0, Math.min(PLOT_X1, ((e.clientX - r.left) / r.width) * CW));
    if (L.hover === null && L.hoverMix < 0.02) L.hoverX = nx;
    L.hover = nx; kick();
  }
  function onLeave() { L.hover = null; kick(); }

  function startLoop() {
    const { canvas, card, u } = nodes, ctx = canvas.getContext('2d');
    const dpr = Math.min(2, Math.max(1, devicePixelRatio || 1));
    const bxc = Math.ceil(BX * u), byc = Math.ceil(BY * u), bx = bxc * dpr, by = byc * dpr;
    canvas.width = Math.ceil(CW * u * dpr + 2 * bx); canvas.height = Math.ceil(CH * u * dpr + 2 * by);
    Object.assign(canvas.style, { left: `${-bxc}px`, top: `${-byc}px`, width: `${canvas.width / dpr}px`, height: `${canvas.height / dpr}px` });
    const { rest: field, lift: bright } = buildField(Math.min(o.width * dpr, Math.max(o.width, 700)), 11);
    const grid = buildGrid(o.width * dpr), halo = buildHalo(o.width);
    const tLand = frac => T_DRAW0 + T_DRAW * inverseEase(frac);
    const roundRect = () => {
      ctx.beginPath(); ctx.moveTo(CR, 0); ctx.arcTo(CW, 0, CW, CH, CR); ctx.arcTo(CW, CH, 0, CH, CR);
      ctx.arcTo(0, CH, 0, 0, CR); ctx.arcTo(0, 0, CW, 0, CR); ctx.closePath();
    };
    const draw = dt => {
      if (started && !reduce && !(L.hover !== null && clock >= T_REST)) clock += dt;
      const t = clock, F = started ? frameAt(t) : frameAt(0);
      if (reduce) F.breath = 0;
      if (L.morph < 1) L.morph = reduce ? 1 : Math.min(1, L.morph + dt / T_MORPH);
      const mk = easeInOut(L.morph), C = L.curve, morphing = L.from && L.morph < 1;
      const ys = morphing ? new Float32Array(CW + 1) : C.ys;
      if (morphing) for (let x = 0; x <= CW; x++) ys[x] = L.from.ys[x] + (C.ys[x] - L.from.ys[x]) * mk;
      const mix = (a, b) => (morphing ? a + (b - a) * mk : b);
      const peakX = mix(L.from?.peakX, C.peakX), lo = mix(L.from?.lo, C.lo), hi = mix(L.from?.hi, C.hi);
      const landed = t >= tLand((peakX + DOT_DX) / CW) && F.dotA > 0.99;
      const want = L.hover !== null && (landed || reduce);
      if (L.hover !== null) L.hoverX = reduce ? L.hover : L.hoverX + (L.hover - L.hoverX) * (1 - Math.exp(-dt * 14));
      L.hoverMix = reduce ? (want ? 1 : 0) : L.hoverMix + ((want ? 1 : 0) - L.hoverMix) * (1 - Math.exp(-dt * 10));
      if (L.valueT < 1) L.valueT = reduce ? 1 : Math.min(1, L.valueT + dt / 0.9);
      const shown = (L.valueFrom + (L.value - L.valueFrom) * easeOut(L.valueT)) * F.num;
      L.shownValue = shown;
      const txt = digits(shown);
      if (nodes.dig.textContent !== txt) nodes.dig.textContent = txt;
      nodes.num.style.opacity = String(F.numA);
      nodes.num.style.transform = `translateY(${(F.numY * 5 * u).toFixed(2)}px)`;
      const blur = Math.abs(F.numY) * 6 * u;
      nodes.num.style.filter = blur > 0.05 ? `blur(${blur.toFixed(2)}px)` : '';

      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const s = dpr * u;
      ctx.setTransform(s, 0, 0, s, bx, by);
      ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(halo, -BX, -BY, CW + 2 * BX, CH + 2 * BY);
      ctx.save(); roundRect(); ctx.clip();
      ctx.drawImage(field, 0, 0, CW, CH);
      if (F.breath > 0.001) { ctx.globalAlpha = F.breath; ctx.drawImage(bright, 0, 0, CW, CH); }
      if (F.grid > 0.001) { ctx.globalAlpha = F.grid; ctx.drawImage(grid, 0, 0, CW, CH); }
      ctx.globalAlpha = 1;
      const x1 = F.draw * CW;
      if (x1 > 0.5) {
        const g = ctx.createLinearGradient(0, 0, CW, 0), head = 0.95 * (1 - smooth((F.draw - 0.8) / 0.2));
        for (let i = 0; i <= 54; i++) {
          const x = (i / 54) * CW;
          let a = lineAlpha(x - peakX - LINE_CENTER);
          if (head > 0.001 && x <= x1 + 10) a = Math.max(a, head * Math.exp(-Math.max(0, x1 - x) / 70));
          g.addColorStop(i / 54, rgba(LINE_COLOR, a));
        }
        ctx.strokeStyle = g; ctx.lineWidth = LINE_W; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
        ctx.beginPath(); ctx.moveTo(0, curveY(ys, 0));
        for (let x = 1; x < x1; x++) ctx.lineTo(x, ys[x]);
        ctx.lineTo(x1, curveY(ys, x1)); ctx.stroke();
      }
      if (F.dotA > 0.001) {
        const restX = peakX + DOT_DX, baseX = Math.min(x1, restX);
        const dx = baseX + (L.hoverX - baseX) * L.hoverMix;
        const dy = curveY(ys, dx) + DOT_DY * (1 - L.hoverMix) * clamp01(baseX / restX);
        const since = t - tLand(restX / CW), pulse = since > 0 && since < 1.1 && !reduce ? since / 1.1 : -1;
        ctx.globalAlpha = F.dotA; ctx.translate(dx, dy); ctx.scale(F.dotS, F.dotS);
        const boost = pulse >= 0 ? Math.sin(Math.PI * Math.min(1, pulse * 1.6)) : 0;
        const hg = ctx.createRadialGradient(0, 0, 0, 0, 0, 30), ha = a => rgba(DOT_GLOW, Math.min(1, a * (1 + 0.9 * boost)));
        [[0, .47], [.5, .47], [17 / 30, .41], [19 / 30, .31], [.7, .17], [23 / 30, .1], [25 / 30, .06], [.9, .03], [1, 0]].forEach(([p, a]) => hg.addColorStop(p, ha(a)));
        ctx.fillStyle = hg; ctx.beginPath(); ctx.arc(0, 0, 30, 0, Math.PI * 2); ctx.fill();
        if (pulse >= 0) {
          ctx.strokeStyle = rgba(PULSE_COLOR, 0.55 * (1 - pulse) ** 2); ctx.lineWidth = 2.2 * (1 - pulse) + 0.6;
          ctx.beginPath(); ctx.arc(0, 0, DOT_R + 26 * easeOut(pulse), 0, Math.PI * 2); ctx.stroke();
        }
        const bg = ctx.createLinearGradient(0, -DOT_R, 0, DOT_R);
        bg.addColorStop(0, DOT_TOP); bg.addColorStop(0.45, DOT_MID); bg.addColorStop(1, DOT_BOTTOM);
        ctx.fillStyle = bg; ctx.beginPath(); ctx.arc(0, 0, DOT_R, 0, Math.PI * 2); ctx.fill();
        ctx.setTransform(s, 0, 0, s, bx, by); ctx.globalAlpha = 1;
        const rd = nodes.read;
        rd.style.opacity = L.hoverMix.toFixed(3);
        rd.style.transform = `translate(${(dx * u).toFixed(1)}px, ${((dy - 26) * u).toFixed(1)}px) translate(-50%, -100%) scale(${(0.92 + 0.08 * L.hoverMix).toFixed(3)})`;
        if (L.hoverMix > 0.01) {
          const idx = Math.round(((Math.max(PLOT_X0, Math.min(PLOT_X1, dx)) - PLOT_X0) / (PLOT_X1 - PLOT_X0)) * (C.n - 1));
          // Read the actual data point under the pointer, not an interpolated curve value.
          const v = o.data[idx] ?? lo + ((PLOT_BOTTOM - curveY(ys, dx)) / (PLOT_BOTTOM - PLOT_TOP)) * (hi - lo);
          const vt = o.formatValue ? o.formatValue(v) : `${Math.round(v)}${o.valueSuffix}`;
          if (nodes.readVal.textContent !== vt) nodes.readVal.textContent = vt;
          nodes.readLab.textContent = o.labels?.[idx] ?? '';
        }
      }
      ctx.restore();
    };
    const busy = () => started && (!reduce || L.morph < 1 || Math.abs(L.hoverMix - (L.hover !== null ? 1 : 0)) > 0.001);
    const tick = () => {
      raf = 0;
      const now = performance.now(), dt = Math.min(0.1, Math.max(0, (now - last) / 1000));
      last = now; draw(dt);
      if (visible && !document.hidden && busy()) raf = requestAnimationFrame(tick);
    };
    kick = () => { if (!raf && visible && !document.hidden) { last = performance.now(); raf = requestAnimationFrame(tick); } };
    draw(0);
    io = new IntersectionObserver(([e]) => {
      visible = e.isIntersecting;
      if (visible) { started = true; kick(); } else if (raf) { cancelAnimationFrame(raf); raf = 0; }
    });
    io.observe(card);
    onVis = () => { if (!document.hidden) kick(); };
    document.addEventListener('visibilitychange', onVis);
  }
  let kick = () => {};

  function teardown() {
    io?.disconnect();
    if (onVis) document.removeEventListener('visibilitychange', onVis);
    if (raf) cancelAnimationFrame(raf);
    raf = 0; kick = () => {};
  }

  mount();
  return {
    update(next) {
      if (next.data && next.data.join() !== o.data.join()) {
        const t = easeInOut(L.morph);
        if (L.from && L.morph < 1) {
          const ys = new Float32Array(CW + 1);
          for (let x = 0; x <= CW; x++) ys[x] = L.from.ys[x] + (L.curve.ys[x] - L.from.ys[x]) * t;
          L.from = { ...L.curve, ys, peakX: L.from.peakX + (L.curve.peakX - L.from.peakX) * t };
        } else L.from = L.curve;
        L.curve = buildCurve(next.data); L.morph = 0;
      }
      if (next.value !== undefined && next.value !== L.value) { L.valueFrom = L.shownValue; L.value = next.value; L.valueT = 0; }
      Object.assign(o, next);
      paintText(); renderMenu(); kick();
    },
    resize(width) {
      if (Math.abs(width - o.width) < 2) return;
      teardown(); o.width = width; mount();
    },
    destroy() {
      teardown();
      removeEventListener('pointerdown', outside); removeEventListener('keydown', esc);
      host.replaceChildren();
    },
  };
}
