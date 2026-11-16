import test from 'node:test';
import assert from 'node:assert/strict';
import { lastNumber, explainMeasured } from './measured-tip.js';

const DATA = {
  risk: { rates: 0.71, stocks: 0.19, oil: 0.03 },
  betas: [{ subject: 'robert', beta: -0.03, lo: -0.051, hi: -0.009, p: 0.006 }, { subject: 'ENB.TO', beta: 0.092, lo: 0.038, hi: 0.145, p: null }],
  scenario: { subject: 'robert', type: 'oil', shock: -30, impact: 1.07, lo: 0.3, hi: 1.85 },
  shields: [{ item: 'GLD', label: 'NEUTRAL', avg: 0.33, up: 14, weeks: 27, p: 1 }],
  cushion: [{ asset: 'usdcad', avg: 0.5, up: 21, weeks: 27 }],
};

test('the number just before a tag is read with its unit, minus signs included', () => {
  assert.deepEqual(lastNumber('it moved about +1.07%'), { value: 1.07, unit: '%' });
  assert.deepEqual(lastNumber('a weekly beta of −0.030'), { value: -0.03, unit: null });
  assert.deepEqual(lastNumber('rates rise 100 bp'), { value: 100, unit: 'bp' });
  assert.deepEqual(lastNumber('rose in 14'), { value: 14, unit: null });
  assert.equal(lastNumber('no figure here'), null);
});

test('a beta is explained with its regression formula, range and p-value', () => {
  const ex = explainMeasured({ before: 'Your portfolio moved about -0.03', data: DATA });
  assert.match(ex.title, /Beta of Robert’s portfolio/);
  assert.match(ex.html, /Cov\(r, r_brent\) \/ Var\(r_brent\)/);
  assert.match(ex.html, /95% range -0\.051 to -0\.009/);
  assert.match(ex.html, /p = 0\.006/);
});

test('a scenario impact shows the shock formula with the actual beta and shock', () => {
  const ex = explainMeasured({ before: 'that implied roughly +1.07%', data: DATA });
  assert.match(ex.title, /Brent -30%/);
  assert.match(ex.html, /e\^\(β · ln\(1 \+ s\/100\)\) − 1/);
  assert.match(ex.html, /β = -0\.030/);
  assert.match(ex.html, /not a forecast/);
  assert.match(explainMeasured({ kind: 'simulated', before: 'no number', data: DATA }).title, /Brent -30%/);
});

test('risk shares, worst-week counts and shields get their own explanations', () => {
  assert.match(explainMeasured({ before: 'Rates explain 0.71', data: DATA }).html, /R² = \+0\.71/);
  const weeks = explainMeasured({ before: 'Gold went up in 14', data: DATA });
  assert.match(weeks.title, /Worst-weeks test/);
  assert.match(weeks.html, /14 of those 27 weeks/);
  assert.match(weeks.html, /Binomial test .*p = 1/);
  assert.match(explainMeasured({ before: 'the dollar averaged +0.50%', data: DATA }).html, /average weekly return in them is <b>\+0\.50%/);
});

test('source tags and unmatched numbers degrade to honest generic text', () => {
  assert.match(explainMeasured({ kind: 'source' }).title, /Source passage/);
  const generic = explainMeasured({ before: 'something 42.5 odd', data: DATA, trace: [{ tool: 'get_portfolio_facts' }, { tool: 'get_portfolio_facts' }] });
  assert.match(generic.title, /Measured/);
  assert.match(generic.html, /never by the language model/);
  assert.match(generic.html, /<code>get_portfolio_facts<\/code>/);
  assert.match(generic.html, /How AION reasoned/);
  assert.match(explainMeasured({}).html, /stored weekly data/);
});

test('backend strings inside explanations are escaped', () => {
  const ex = explainMeasured({ before: 'beta 0.5', data: { betas: [{ subject: '<img src=x>', beta: 0.5, lo: 0.1, hi: 0.9 }] } });
  assert.doesNotMatch(ex.title + ex.html, /<img/);
  assert.match(ex.title, /&lt;img src=x&gt;/);
});
