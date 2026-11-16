// A small, safe Markdown subset for agent answers: paragraphs, line breaks, "-"/"*" and "1." lists,
// "#" headings, **bold**, *italic* and `code`. Everything is HTML-escaped first; only these tags are added.
import { escapeHTML as esc } from './formatters.js';

const inline = text => esc(text)
  .replace(/`([^`\n]+)`/g, '<code>$1</code>')
  .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
  .replace(/(^|[\s(])\*([^*\s][^*\n]*?)\*(?=[\s).,;:!?]|$)/g, '$1<em>$2</em>');

export function renderMarkdown(markdown) {
  const out = [];
  let para = [], list = null;
  const flush = () => { if (para.length) { out.push(`<p>${para.map(inline).join('<br>')}</p>`); para = []; } };
  const close = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const raw of String(markdown ?? '').replace(/\r\n?/g, '\n').split('\n')) {
    const line = raw.trimEnd();
    if (!line.trim()) { flush(); close(); continue; }
    const bullet = line.match(/^\s*[-*•]\s+(.+)$/), ordered = line.match(/^\s*\d{1,3}[.)]\s+(.+)$/), heading = line.match(/^\s*#{1,6}\s+(.+)$/);
    if (heading) { flush(); close(); out.push(`<p class="md-h">${inline(heading[1])}</p>`); continue; }
    if (bullet || ordered) {
      flush();
      const kind = bullet ? 'ul' : 'ol';
      if (list !== kind) { close(); out.push(`<${kind}>`); list = kind; }
      out.push(`<li>${inline((bullet ?? ordered)[1])}</li>`);
      continue;
    }
    close();
    para.push(line.trim());
  }
  flush(); close();
  return out.join('');
}
