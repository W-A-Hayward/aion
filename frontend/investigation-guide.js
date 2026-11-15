import { escapeHTML as esc } from './formatters.js';

// Explanatory examples only. No research CSVs, PDFs, estimates, API or AWS access.
export const GUIDE_TOPICS = Object.freeze(['holdings', 'mechanisms', 'reliability']);

export function guideContent(topic, ticker, expert = false) {
  const selected = String(ticker || 'the selected investment');
  const topics = {
    holdings: {
      title: `Start with what ${selected} actually owns.`,
      explanation: 'For an ETF, a dated holdings file identifies its companies and their weights. The weight is the share of the fund invested in that holding; it does not tell you how much oil risk that company contributes.',
      points: [
        ['What to look for', 'Company, share class, weight, sector and the official holdings date. Cash and futures need separate treatment.'],
        ['Why the date matters', 'Today’s composition can differ from the portfolio held during the historical price sample.'],
        ['What would complete the explanation', 'Comparable estimates for the holdings, the weight covered by usable data, and an honest account of the missing positions.'],
      ],
      expert: 'Current-composition weight × comparable beta is an approximation, not exact historical attribution. Use a common return definition, benchmark, currency, sample and controls. Joint uncertainty needs covariance or a suitable bootstrap. Sector weight and beta have different units.',
      action: 'Explore the documented XIU holdings', target: 'evidence-desk',
    },
    mechanisms: {
      title: 'Oil can reach a business through more than one route.',
      explanation: 'These are mechanisms to investigate, not findings about the selected investment. A company can face several at once, with effects that partly offset each other.',
      points: [
        ['An oil producer · selling prices', 'The price received for production depends on its benchmark, regional price differences, currency and costs.'],
        ['A railway · costs and customers', 'Diesel costs money, surcharges may recover some of it, and energy-related freight brings revenue. The timing and mix matter.'],
        ['A bank · credit exposure', 'Loans to oil-and-gas businesses create a credit link. Loan balances, expected losses and the bank’s share-price sensitivity are different measures.'],
      ],
      expert: 'Treat operating channels as documentary evidence. Separate a reported fact from the researcher’s interpretation. Company cash-flow sensitivities are not regressions of equity returns on Brent. Do not infer causality, a stock-return sign or complete pass-through from a business disclosure.',
      action: 'Open the Evidence Desk', target: 'evidence-desk',
    },
    reliability: {
      title: 'Check the estimate and the explanation separately.',
      explanation: 'Beta describes a historical relationship between returns and oil. The confidence interval shows uncertainty about that estimate. A convincing business explanation still needs a statistical check.',
      points: [
        ['Measured relationship', 'Read the beta, confidence interval, number of weeks and stability checks. If the interval crosses zero, the sample does not settle the direction.'],
        ['Documented explanation', 'Open the issuer’s report at the exact page. Keep the quote, table heading, units, footnotes and reporting period together.'],
        ['What “verified” should mean', 'A matching document hash identifies the file. An exact quote checks the transcription. Neither proves that oil caused a stock-price move.'],
      ],
      expert: 'Check the regression’s controls, currency, sample dates, HAC standard errors, rolling estimates and out-of-sample results. Track source provenance, PDF identity and passage verification separately. Ceteris-paribus operating scenarios are not share-price forecasts or confidence intervals.',
      action: 'Review the current estimate', target: 'headline',
    },
  };
  if (!Object.hasOwn(topics, topic)) throw new Error('Unknown investigation guide topic');
  return { ...topics[topic], ticker: selected, expertVisible: expert === true };
}

export function renderGuidePanel(content) {
  return `<div class="guide-copy"><h3>${esc(content.title)}</h3><p>${esc(content.explanation)}</p></div>
    <dl class="guide-reasons">${content.points.map(([title, description]) => `<div><dt>${esc(title)}</dt><dd>${esc(description)}</dd></div>`).join('')}</dl>
    <details class="guide-detail" ${content.expertVisible ? 'open' : ''}><summary>Method and limitations</summary><p>${esc(content.expert)}</p></details>
    <div class="guide-actions"><button type="button" class="ghost-button" data-guide-target="${esc(content.target)}">${esc(content.action)} <span aria-hidden="true">↗</span></button><span>Same facts in Beginner and Expert.</span></div>`;
}

export function initInvestigationGuide(doc = document) {
  const root = doc.querySelector('#investigation-guide');
  if (!root) return;
  const panel = root.querySelector('#guide-panel');
  const tabs = [...root.querySelectorAll('[data-guide-topic]')];
  const ticker = doc.querySelector('#chat-ticker');
  let topic = 'mechanisms';
  function draw() {
    const expert = doc.querySelector('[data-mode="expert"]')?.getAttribute('aria-pressed') === 'true';
    panel.innerHTML = renderGuidePanel(guideContent(topic, ticker?.value, expert));
    panel.setAttribute('aria-labelledby', `guide-tab-${topic}`);
    for (const tab of tabs) {
      tab.setAttribute('aria-selected', String(tab.dataset.guideTopic === topic));
      tab.tabIndex = tab.dataset.guideTopic === topic ? 0 : -1;
    }
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => { topic = tab.dataset.guideTopic; draw(); });
    tab.addEventListener('keydown', event => {
      const next = { ArrowRight: (index + 1) % tabs.length, ArrowLeft: (index + tabs.length - 1) % tabs.length,
        Home: 0, End: tabs.length - 1 }[event.key];
      if (next === undefined) return;
      event.preventDefault(); tabs[next].click(); tabs[next].focus();
    });
  });
  root.addEventListener('click', event => {
    const button = event.target.closest('[data-guide-target]');
    if (!button) return;
    if (button.dataset.guideTarget !== 'evidence-desk') doc.querySelector('.workspace-nav [data-view="research"]')?.click();
    const target = doc.getElementById(button.dataset.guideTarget);
    // Loading/error states can hide the research body. Send the reader to the visible status instead.
    const destination = target?.closest('[hidden]') ? doc.getElementById('status') : target;
    if (destination) {
      destination.setAttribute('tabindex', '-1');
      destination.scrollIntoView({ behavior: 'instant', block: 'start' });
      destination.focus({ preventScroll: true });
    }
  });
  ticker?.addEventListener('change', draw);
  doc.querySelector('#field')?.addEventListener('click', () => queueMicrotask(draw));
  const observer = new MutationObserver(draw);
  doc.querySelectorAll('[data-mode]').forEach(button => observer.observe(button,
    { attributes: true, attributeFilter: ['aria-pressed'] }));
  // Watchlist and workspace selections update the chat context programmatically.
  const context = doc.querySelector('#chat-context');
  if (context) observer.observe(context, { childList: true, characterData: true, subtree: true });
  root.querySelector('.guide-tabs').hidden = false;
  draw();
}

if (typeof document !== 'undefined') initInvestigationGuide();
