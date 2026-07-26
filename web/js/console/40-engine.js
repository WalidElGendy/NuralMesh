/* ==========================================================================
   The reasoning engine.

   v0.3 sent one prompt to one model and rendered whatever came back, with
   `stream: False`, so a reply appeared as one block after a long silence.
   This runs a small pipeline instead, and shows it running:

       route  →  recall  →  [plan | ground]  →  draft  →  verify

   Every step is optional and the router decides, so "hi" costs one cheap call
   while a research question costs four. Each step reports its timing to the
   pipeline strip in the UI.

   Endpoints used (all on the beta's own API):
     POST /api/agents/{id}/turn/stream   SSE draft — added in agents.py v0.4
     POST /api/agents/{id}/turn          buffered fallback (v0.3 compatible)
     POST /api/agents/complete           route | plan | verify | title
     POST /api/search                    web grounding (mesh_search.py)
   ========================================================================== */

import { CFG, S, api, apiRaw, clamp } from './00-core.js';
import { MODES } from './30-modes.js';
import { searchNotes } from './50-graph.js';
import { searchVault } from './55-vault.js';

/* --------------------------- pipeline sub-steps -------------------------- */

const CHITCHAT = /^\s*(hi|hey|hello|yo|sup|salam|سلام|مرحبا|أهلا|hola|bonjour|test|ping|thanks|thank you|شكرا|ok|okay)[\s!.،,?]*$/i;

/** Ask the server to classify the request. A greeting skips the call entirely. */
export async function route(query) {
  if (CHITCHAT.test(query)) {
    return { intent: 'chitchat', needs_web: false, needs_memory: false,
             quantitative: false, complexity: 1, cheap: true };
  }
  try {
    const r = await api('/agents/complete', {
      method: 'POST',
      body: JSON.stringify({ task: 'route', content: query.slice(0, 2000) }),
    });
    if (r?.result?.intent) return r.result;
  } catch { /* fall through */ }

  // Heuristics keep the pipeline working if the classifier call fails.
  return {
    intent: 'factual',
    needs_web:    /\b(latest|current|today|202[4-9]|news|price|release|who is|now)\b|الآن|اليوم|أحدث/i.test(query),
    needs_memory: /\b(that|this|earlier|we discussed|my |our )\b|\[\[/i.test(query),
    quantitative: /\b(compare|trend|breakdown|forecast|revenue|cost|market|growth|%|per|rate)\b|مقارنة|تحليل|نمو|سوق/i.test(query),
    complexity: query.length > 220 ? 4 : 2,
  };
}

/**
 * Recall from the user's own material.
 *
 * Deliberately client-side: the knowledge graph lives in the browser (and, if
 * connected, in the user's Obsidian vault on 127.0.0.1). No note text is sent
 * anywhere until it is chosen as context for a turn.
 */
export async function recall(query, { limit = 6 } = {}) {
  const local = searchNotes(query, limit);
  let vault = [];
  if (S.vault.connected) {
    try { vault = await searchVault(query, limit); } catch { /* offline */ }
  }
  return [...local, ...vault]
    .sort((a, b) => (b.score || 0) - (a.score || 0))
    .slice(0, limit);
}

/** Web grounding through the server-side proxy, so no API key reaches the browser. */
export async function ground(query, { limit = 6 } = {}) {
  try {
    const r = await api('/search', {
      method: 'POST',
      body: JSON.stringify({ q: query.slice(0, 400), count: limit }),
    });
    return r?.results || [];
  } catch { return []; }
}

export async function plan(query) {
  const r = await api('/agents/complete', {
    method: 'POST',
    body: JSON.stringify({ task: 'plan', content: query }),
  });
  return r?.result || null;
}

export async function verify({ query, draft, sources }) {
  const r = await api('/agents/complete', {
    method: 'POST',
    body: JSON.stringify({ task: 'verify', content: query, draft, sources: sources || [] }),
  });
  return r?.result || { ok: true, issues: [], confidence: null };
}

/* ------------------------------- the draft ------------------------------- */

let STREAM_SUPPORTED = null;   // probed once, then cached

/**
 * Stream one turn. Falls back to the buffered v0.3 endpoint when the streaming
 * route is not deployed yet, so the client works against either backend.
 */
async function draft({ agentId, content, mode, context, onDelta, signal }) {
  if (STREAM_SUPPORTED !== false) {
    try {
      const res = await apiRaw(`/agents/${agentId}/turn/stream`, {
        method: 'POST', signal,
        body: JSON.stringify({ content, mode, context }),
      });
      if (res.ok && (res.headers.get('content-type') || '').includes('event-stream')) {
        STREAM_SUPPORTED = true;
        return await readSSE(res, onDelta);
      }
      if (res.status === 404 || res.status === 405) STREAM_SUPPORTED = false;
      else if (!res.ok) throw new Error(`turn ${res.status}: ${(await res.text()).slice(0, 160)}`);
    } catch (e) {
      if (e.name === 'AbortError') throw e;
      if (STREAM_SUPPORTED === null) STREAM_SUPPORTED = false;
      else throw e;
    }
  }

  // Buffered path — no tokens arrive until the whole answer is ready.
  const t0 = performance.now();
  const r = await api(`/agents/${agentId}/turn`, {
    method: 'POST', signal,
    body: JSON.stringify({ content, mode, context }),
  });
  const text = r?.assistant_message?.content || '';
  onDelta?.(text);
  return {
    text,
    meta: { ms: performance.now() - t0, tokens: Math.ceil(text.length / 4), buffered: true },
    agent: r?.agent || null,
    messageId: r?.assistant_message?.id || null,
  };
}

async function readSSE(res, onDelta) {
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  const t0 = performance.now();
  let buf = '', text = '', meta = {}, agent = null, messageId = null, ttft = null, err = null;

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop();
    for (const line of lines) {
      if (!line.startsWith('data:')) continue;
      const payload = line.slice(5).trim();
      if (!payload || payload === '[DONE]') continue;
      let f; try { f = JSON.parse(payload); } catch { continue; }

      if (f.type === 'delta' && f.v) {
        if (ttft == null) ttft = performance.now() - t0;
        text += f.v;
        onDelta?.(f.v);
      } else if (f.type === 'done') {
        meta = f.meta || {};
        agent = f.agent || null;
        messageId = f.message_id || null;
      } else if (f.type === 'error') {
        err = f.detail || 'stream_error';
      } else if (f.type === 'start') {
        meta.model = f.model;
      }
    }
  }
  if (err && !text) throw new Error(err);

  const ms = meta.latency_ms ?? (performance.now() - t0);
  const tokens = meta.tokens ?? Math.ceil(text.length / 4);
  return {
    text,
    meta: {
      ...meta,
      ms,
      ttft: meta.ttft_ms ?? ttft,
      tokens,
      tps: tokens / Math.max((ms - (meta.ttft_ms ?? ttft ?? 0)) / 1000, 0.001),
    },
    agent,
    messageId,
  };
}

/* ------------------------------ orchestration ---------------------------- */

/**
 * Run one turn.
 * hooks.onStep(name, state, info)  state: 'run' | 'done' | 'skip'
 * hooks.onDelta(chunk)
 */
export async function runTurn({ agentId, query, mode, hooks = {}, signal }) {
  const step = (n, st, info) => hooks.onStep?.(n, st, info);
  const timings = {};
  const timed = async (name, fn) => {
    const t = performance.now();
    step(name, 'run');
    try {
      const out = await fn();
      timings[name] = performance.now() - t;
      step(name, 'done', { ms: timings[name] });
      return out;
    } catch (e) {
      timings[name] = performance.now() - t;
      step(name, 'skip', { ms: timings[name], error: e.message });
      return null;
    }
  };

  const cfg = MODES[mode] || MODES.ask;

  const r = (await timed('route', () => route(query))) || {};

  let memory = [];
  if (cfg.steps.includes('recall') && r.needs_memory !== false && !r.cheap) {
    memory = (await timed('recall', () => recall(query))) || [];
  } else step('recall', 'skip');

  let planOut = null;
  if (cfg.steps.includes('plan') && (r.complexity ?? 3) >= 3 && !r.cheap) {
    planOut = await timed('plan', () => plan(query));
  } else if (cfg.steps.includes('plan')) step('plan', 'skip');

  let sources = [];
  const wantsWeb = cfg.steps.includes('ground') || r.needs_web === true;
  if (wantsWeb && !r.cheap) {
    sources = (await timed('ground', () => ground(query))) || [];
  } else if (cfg.steps.includes('ground')) step('ground', 'skip');

  // Retrieval travels with the turn; the server owns the prompt assembly.
  const context = {
    quantitative: r.quantitative === true,
    memory: memory.map(m => (m.title ? `${m.title}: ` : '') + String(m.text).slice(0, 600)),
    sources,
    plan: planOut,
  };

  step('draft', 'run');
  const tDraft = performance.now();
  const out = await draft({
    agentId, content: query, mode, context, onDelta: hooks.onDelta, signal,
  });
  timings.draft = performance.now() - tDraft;
  step('draft', 'done', { ms: timings.draft });

  let review = null;
  if (cfg.steps.includes('verify') && out.text.length > 240 && !r.cheap) {
    review = await timed('verify', () => verify({ query, draft: out.text, sources }));
  } else step('verify', 'skip');

  return { ...out, route: r, memory, sources, plan: planOut, review, timings };
}

/* ----------------------------- cost + telemetry -------------------------- */

export function costModel({ tokens }) {
  const mesh = (tokens / 1e6) * CFG.MESH_USD_PER_MTOK;
  const base = (tokens / 1e6) * CFG.BASELINE_USD_PER_MTOK;
  return { mesh, base, saved: base - mesh, ratio: base / Math.max(mesh, 1e-9) };
}

export async function titleFor(query) {
  try {
    const r = await api('/agents/complete', {
      method: 'POST', body: JSON.stringify({ task: 'title', content: query }),
    });
    return (r?.result || '').trim().slice(0, 60) || null;
  } catch { return null; }
}

/* --------------------------------- threads -------------------------------- */

export const threads = {
  list:   ()          => api('/agents'),
  create: (title)     => api('/agents', { method: 'POST', body: JSON.stringify({ title: title || null }) }),
  rename: (id, title) => api('/agents/' + id, { method: 'PATCH', body: JSON.stringify({ title }) }),
  remove: (id)        => api('/agents/' + id, { method: 'DELETE' }),
  messages: (id)      => api('/agents/' + id + '/messages'),
};

/**
 * Provider/mesh status.
 *
 * The beta has no public node telemetry endpoint yet, so this reports what the
 * turn responses actually say — the honest version — rather than inventing a
 * node count. When /api/providers/public ships it is picked up automatically.
 */
let MESH_ENDPOINT = null;    // null = unprobed, false = not deployed

/**
 * Mesh telemetry.
 *
 * Probed once. If /api/mesh/status is not deployed the client stops asking
 * rather than logging a 404 on every refresh, and the pane says plainly that
 * telemetry is unavailable instead of inventing a node count.
 */
export async function meshStatus() {
  if (MESH_ENDPOINT === false) return null;
  try {
    const r = await api('/mesh/status');
    MESH_ENDPOINT = true;
    return r;
  } catch (e) {
    if (MESH_ENDPOINT === null) MESH_ENDPOINT = false;
    return null;
  }
}
