import { escapeHTML as esc, sourceURL, finite, number } from './formatters.js';

export function renderAgentAnswer(host, result, { persona, level, ticker }) {
  const citations = result.citations ?? [], calls = result.toolCalls ?? [];
  host.innerHTML = `<p class="answer-label">Backend answer · ${esc(persona)} · ${esc(level)} · ${esc(ticker)}</p>
    <p class="note">This answer has its own backend sources. The charts above retain their selected data source. AWS deployment and document accuracy are not independently verified.</p>
    <div class="agent-prose">${esc(result.answer)}</div>
    <details><summary>Evidence returned (${citations.length})</summary>
    ${citations.length ? citations.map(citation => {
      const link = sourceURL(citation.source_url);
      return `<article class="agent-citation"><p class="label">${esc(citation.ticker || 'Ticker not supplied')} · ${esc(citation.channel || 'Channel not supplied')}</p>
        <blockquote>${esc(citation.text || 'No passage supplied.')}</blockquote>
        <p class="note">Section: ${esc(citation.section || 'Not supplied')}. Original title, issuer and publication date: not supplied by this API.</p>
        ${link ? `<a href="${esc(link)}" target="_blank" rel="noopener noreferrer">Open supplied source ↗</a><p class="note">Link not independently verified.</p>` : `<p class="note">No public source link supplied. ${esc(citation.source_url || '')}</p>`}</article>`;
    }).join('') : '<p>No documentary evidence returned. Do not treat the answer as verified.</p>'}</details>
    <details><summary>Calculations and tool calls (${calls.length})</summary>
      <p class="note">Raw tool outputs can be truncated by the backend. They are not silently substituted into the charts.</p>
      ${calls.map(call => `<article class="agent-citation"><h4>${esc(call.name || 'Unnamed tool')}</h4><pre>${esc(JSON.stringify(call.input ?? {}, null, 2))}</pre><pre>${esc(typeof call.output === 'string' ? call.output : JSON.stringify(call.output ?? null, null, 2))}</pre></article>`).join('') || '<p>No tool details returned.</p>'}
    </details><p class="note">Job ${esc(result.jobId)}${finite(result.durationMs) ? ` · ${number(result.durationMs / 1000, 1)} seconds` : ''}. Session ID reused for follow-ups; this backend has no explicit history store. Ask self-contained questions.</p>`;
}
