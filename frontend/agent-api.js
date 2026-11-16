import { config, CORE_TICKERS } from './config.js';
import { sourceURL } from './formatters.js';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const SESSION = /^[A-Za-z0-9-]{1,100}$/;
export const agentConfigured = (settings = config) => Boolean(settings.submitUrl && settings.statusUrl);
const SAMPLE_PERSONAS = ['robert', 'amira', 'mateo'];
const HOLDING_TICKERS = new Set(CORE_TICKERS);

/** A custom portfolio as lambdas/submit accepts it: 1-14 core tickers, no duplicates, weights summing to 1. */
export function backendHoldings(holdings) {
  if (!Array.isArray(holdings) || !holdings.length || holdings.length > HOLDING_TICKERS.size) return null;
  const seen = new Set();
  const out = [];
  for (const h of holdings) {
    const w = Number(h?.weight);
    if (!HOLDING_TICKERS.has(h?.ticker) || seen.has(h.ticker) || !(w > 0 && w <= 1)) return null;
    seen.add(h.ticker);
    out.push({ ticker: h.ticker, weight: Math.round(w * 1e6) / 1e6 });
  }
  return Math.abs(out.reduce((t, h) => t + h.weight, 0) - 1) <= 0.005 ? out : null;
}

// The backend lets only the browser that submitted a job read it back (lambdas/submit, lambdas/status).
// This random secret identifies this browser; it is never shown and only its hash is stored server-side.
export const SESSION_TOKEN_KEY = 'cascade.session-token';
const TOKEN = /^[A-Za-z0-9_-]{32,128}$/;
let memoryToken;
export function sessionToken(storage = globalThis.localStorage) {
  try { const saved = storage?.getItem(SESSION_TOKEN_KEY); if (TOKEN.test(saved ?? '')) return saved; } catch {}
  if (!memoryToken) {
    const bytes = crypto.getRandomValues(new Uint8Array(32));
    memoryToken = btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  try { storage?.setItem(SESSION_TOKEN_KEY, memoryToken); } catch {}
  return memoryToken;
}

function url(value) {
  const resolved = new URL(value, globalThis.location?.href);
  if (!sourceURL(resolved.href)) throw Error('API URLs must use HTTP or HTTPS without embedded credentials.');
  return resolved.href;
}

function pause(ms, signal) {
  return new Promise((resolve, reject) => {
    signal.throwIfAborted();
    const aborted = () => { clearTimeout(timer); reject(signal.reason); };
    const timer = setTimeout(() => { signal.removeEventListener('abort', aborted); resolve(); }, ms);
    signal.addEventListener('abort', aborted, { once: true });
  });
}

const VERDICTS = new Set(['NOT LINKED', 'MATERIAL', 'WORKING', 'REMOVED', 'BROKEN', 'HIDDEN', 'MINOR', 'MYTH', 'REAL', 'NEUTRAL', 'CONFIRMED', 'PARTIAL', 'UNKNOWN']);
/**
 * The finished answer, from either API shape: a string (before docs/api_contract.md) or the contract object
 * {verdict, headline, text, refusal, caveat}. Returns null when there is nothing to show.
 */
export function normalizeAnswer(answer) {
  if (typeof answer === 'string') return answer.trim() ? { text: answer, verdict: null, headline: null, refusal: false, caveat: null } : null;
  if (!answer || typeof answer !== 'object' || Array.isArray(answer)) return null;
  const str = v => (typeof v === 'string' && v.trim() ? v.trim().slice(0, 2000) : null);
  const text = typeof answer.text === 'string' ? answer.text : '';
  const refusal = answer.refusal === true;
  if (!text.trim() && !refusal) return null;
  // The agent opens with "VERDICT — headline" (prompts/agent_instructions.md); use that when the field is empty.
  const lead = text.trimStart().replace(/^[*_#>\s]+/, '').match(/^([A-Z][A-Z ]{2,14}?)\s*[*_]*\s*[—–:-]/)?.[1];
  const verdict = (str(answer.verdict) ?? lead ?? '').toUpperCase().trim() || null;
  return { text: text || 'The agent declined this request.', verdict: verdict && VERDICTS.has(verdict) ? verdict : null,
    headline: str(answer.headline), refusal, caveat: str(answer.caveat) };
}

// Dependency injection lets local tests exercise the real transport contract without AWS.
export function createAgentClient(settings = config, transport = globalThis.fetch, wait = pause, token = sessionToken) {
  return async function ask({ question, persona, level, holdings, sessionId, signal, onProgress = () => {} }) {
    if (!agentConfigured(settings)) throw Error('Chat API is not configured. Local explanations are available; no request was sent.');
    if (!settings.statusUrl.includes('{id}')) throw Error('The status URL must contain {id}.');
    const submit = url(settings.submitUrl);
    url(settings.statusUrl.replace('{id}', '00000000-0000-0000-0000-000000000000'));
    if (typeof question !== 'string' || !question.trim() || question.length > 1000) throw Error('Use a question of 1–1000 characters.');
    if (!SAMPLE_PERSONAS.includes(persona) && persona !== 'custom') throw Error('Choose Robert, Amira, Mateo or your own portfolio.');
    const custom = persona === 'custom' ? backendHoldings(holdings) : null;
    if (persona === 'custom' && !custom) throw Error('Your portfolio needs 1–14 supported tickers with weights adding up to 100%.');
    if (!['beginner', 'expert'].includes(level)) throw Error('Choose Beginner or Expert.');
    if (sessionId !== undefined && !SESSION.test(sessionId)) throw Error('Invalid conversation session.');
    const deadline = AbortSignal.timeout(settings.jobTimeoutMs);
    const lifetime = signal ? AbortSignal.any([signal, deadline]) : deadline;
    const request = async (endpoint, options = {}) => {
      lifetime.throwIfAborted();
      const response = await transport(endpoint, { ...options, credentials: 'omit', cache: 'no-store',
        headers: { Accept: 'application/json', 'X-Cascade-Session': token(), ...options.headers },
        signal: AbortSignal.any([lifetime, AbortSignal.timeout(settings.timeoutMs)]),
      });
      if (response.status === 429) throw Error('Too many questions in the last minute. Wait a moment and try again.');
      if (response.status === 401) throw Error('The chat API rejected this browser session. Reload the page and try again.');
      if (!response.ok) throw Error(`Chat request failed (HTTP ${response.status}). Check the endpoint and its CORS configuration.`);
      return response.json();
    };
    onProgress({ status: 'SUBMITTING' });
    // Never automatically retry POST: a timed-out submission may already have queued a job.
    const job = await request(submit, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: question.trim(), persona, level, ...(custom ? { holdings: custom } : {}), ...(sessionId ? { sessionId } : {}) }),
    });
    if (!UUID.test(job?.jobId) || !SESSION.test(job?.sessionId ?? '')) throw Error('The submit response is missing a valid jobId or sessionId.');
    onProgress({ status: 'PENDING', ...job });
    while (true) {
      const result = await request(url(settings.statusUrl.replace('{id}', encodeURIComponent(job.jobId))));
      if (result?.jobId !== job.jobId || !['PENDING', 'RUNNING', 'DONE', 'FAILED'].includes(result?.status)) throw Error('The status response does not match this job or has an unknown status.');
      onProgress({ ...result, sessionId: job.sessionId });
      if (result.status === 'FAILED') throw Error(typeof result.error === 'string' ? result.error : 'The backend job failed.');
      if (result.status === 'DONE') {
        const answer = normalizeAnswer(result.answer);
        if (!answer) throw Error('The completed job returned no answer.');
        for (const field of ['citations', 'toolCalls', 'trace', 'stages']) {
          if (result[field] !== undefined && (!Array.isArray(result[field]) || result[field].some(row => !row || typeof row !== 'object' || Array.isArray(row)))) throw Error(`Invalid ${field} in the completed job.`);
        }
        // `answer` stays a string for existing callers; the contract's other answer fields go in answerMeta.
        return { ...result, answer: answer.text, answerMeta: answer, sessionId: job.sessionId };
      }
      await wait(settings.pollIntervalMs, lifetime);
    }
  };
}

export const askBackend = createAgentClient();
