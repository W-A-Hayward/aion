import test from 'node:test';
import assert from 'node:assert/strict';
import { guideContent, renderGuidePanel, GUIDE_TOPICS } from './investigation-guide.js';

test('Beginner and Expert retain identical underlying explanations', () => {
  for (const topic of GUIDE_TOPICS) {
    const beginner = guideContent(topic, 'XIU.TO', false);
    const expert = guideContent(topic, 'XIU.TO', true);
    assert.deepEqual({ ...beginner, expertVisible: true }, expert);
    assert.doesNotMatch(renderGuidePanel(beginner), /class="guide-detail" open/);
    assert.match(renderGuidePanel(expert), /class="guide-detail" open/);
  }
});
test('ticker labels are escaped and an unknown topic cannot inject content', () => {
  const html = renderGuidePanel(guideContent('holdings', '<img src=x onerror=alert(1)>'));
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
  assert.throws(() => guideContent('__proto__', 'XIU.TO'));
});
test('mechanisms are exploratory and do not create estimates or selected-company findings', () => {
  const c = guideContent('mechanisms', 'RY.TO');
  assert.match(c.explanation, /not findings about the selected investment/);
  assert.equal(c.points.length, 3);
  assert.equal(c.beta, undefined);
  assert.match(c.expert, /Do not infer causality/);
});
