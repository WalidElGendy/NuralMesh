/* ==========================================================================
   NeuralMesh Console — core

   Talks to the beta's own API (`/api/*`, proxied by vercel.json to
   api.beta.meshnet.co) with the bearer token the login flow already stores in
   localStorage as `nm_access_token`. Same auth contract as the
   web/js/chat/api.js it replaces — nothing about sign-in changes.

   Design intent (why this looks nothing like Grok / Kimi / ChatGPT):
     1. An ANALYST CONSOLE, not a chat bubble column: threads / conversation /
        canvas.
     2. Every answer carries visible PROVENANCE — which model or node served
        it, latency, tokens/s, cost against a centralised provider.
     3. Every answer carries a visible REASONING PIPELINE with real timings.
     4. Data in an answer renders as an interactive CHART.
     5. Conversations form a linked KNOWLEDGE GRAPH (the Obsidian model):
        [[wiki-links]], backlinks, tags, graph view, optional real-vault sync.
   ========================================================================== */

'use strict';

/* ----------------------------- configuration ----------------------------- */

export const CFG = {
  API: '/api',
  LOGIN_URL: '/login.html',
  TOKEN_KEY: 'nm_access_token',
  // Comparison baseline for the "cost vs centralised" chip, USD / 1M tokens.
  BASELINE_USD_PER_MTOK: 10.00,
  MESH_USD_PER_MTOK: 0.89,
  MAX_CONTEXT_TURNS: 12,
};

/* -------------------------------- helpers -------------------------------- */

export const $  = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export const esc = (s) => String(s ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

export const uid = () => (crypto.randomUUID ? crypto.randomUUID()
  : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
      const r = Math.random() * 16 | 0;
      return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
    }));

export const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));

export function fmt(n, opts = {}) {
  if (n == null || Number.isNaN(n)) return '—';
  const abs = Math.abs(n);
  if (opts.pct) return (n * 100).toFixed(opts.dp ?? 1) + '%';
  if (opts.usd) {
    const sign = n < 0 ? '-' : '';
    if (abs === 0)   return '$0';
    if (abs >= 1e6)  return sign + '$' + (abs / 1e6).toFixed(abs >= 1e7 ? 0 : 1) + 'M';
    if (abs >= 1e4)  return sign + '$' + (abs / 1e3).toFixed(abs >= 1e5 ? 0 : 1) + 'k';
    if (abs >= 100)  return sign + '$' + Math.round(abs).toLocaleString();
    if (abs >= 1)    return sign + '$' + abs.toFixed(2);
    if (abs >= 0.01) return sign + '$' + abs.toFixed(3);
    return sign + '$' + abs.toPrecision(2);
  }
  if (opts.ms) return abs >= 1000 ? (n / 1000).toFixed(2) + 's' : Math.round(n) + 'ms';
  if (abs >= 1e9) return (n / 1e9).toFixed(1).replace(/\.0$/, '') + 'B';
  if (abs >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
  if (abs >= 1e4) return (n / 1e3).toFixed(1).replace(/\.0$/, '') + 'k';
  if (Number.isInteger(n)) return n.toLocaleString();
  return n.toLocaleString(undefined, { maximumFractionDigits: opts.dp ?? 2 });
}

export function relTime(iso) {
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (d < 60)     return 'now';
  if (d < 3600)   return Math.floor(d / 60) + 'm';
  if (d < 86400)  return Math.floor(d / 3600) + 'h';
  if (d < 604800) return Math.floor(d / 86400) + 'd';
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

/* The beta had no RTL support at all, so Arabic rendered left-to-right. */
const RTL_RE = /[֐-׿؀-ۿ܀-ݏݐ-ݿࢠ-ࣿיִ-﷿ﹰ-﻿]/;
export const isRTL = (s) => {
  const m = String(s || '').match(/\p{L}/gu);
  if (!m) return false;
  return m.filter(c => RTL_RE.test(c)).length / m.length > 0.3;
};
export const dirOf = (s) => (isRTL(s) ? 'rtl' : 'ltr');

/* --------------------------------- icons --------------------------------- */

const I = (d) =>
  `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"
        aria-hidden="true">${d}</svg>`;

export const ICON = {
  chat:    I('<path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-5.1A8.4 8.4 0 0 1 12 3a8.4 8.4 0 0 1 9 8.5Z"/>'),
  graph:   I('<circle cx="5" cy="6" r="2.2"/><circle cx="19" cy="8" r="2.2"/><circle cx="12" cy="18" r="2.2"/><path d="m7 7 10 1M6.6 8l4.4 8M17.6 10l-4.6 6.4"/>'),
  chart:   I('<path d="M3 3v16.5A1.5 1.5 0 0 0 4.5 21H21"/><path d="M7 15l3.5-4.5 3 3L18 7"/>'),
  mesh:    I('<circle cx="12" cy="12" r="2"/><circle cx="5" cy="5" r="1.8"/><circle cx="19" cy="5" r="1.8"/><circle cx="5" cy="19" r="1.8"/><circle cx="19" cy="19" r="1.8"/><path d="m6.4 6.4 4.2 4.2m2.8 2.8 4.2 4.2M17.6 6.4l-4.2 4.2m-2.8 2.8-4.2 4.2"/>'),
  vault:   I('<path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H10l2 2.5h6.5A1.5 1.5 0 0 1 20 8v10.5a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5Z"/><path d="M9 13h6"/>'),
  search:  I('<circle cx="11" cy="11" r="6.5"/><path d="m20 20-3.6-3.6"/>'),
  plus:    I('<path d="M12 5v14M5 12h14"/>'),
  send:    I('<path d="M4.5 12h13M12 5.5 18.5 12 12 18.5"/>'),
  stop:    I('<rect x="7" y="7" width="10" height="10" rx="1.5"/>'),
  panelL:  I('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>'),
  panelR:  I('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>'),
  copy:    I('<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>'),
  refresh: I('<path d="M20 11a8 8 0 1 0-.6 4"/><path d="M20 5v6h-6"/>'),
  sun:     I('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
  moon:    I('<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z"/>'),
  down:    I('<path d="M12 5v14M6 13l6 6 6-6"/>'),
  link:    I('<path d="M10 13.5a4 4 0 0 0 5.7.4l3-3a4 4 0 0 0-5.7-5.7l-1.5 1.5"/><path d="M14 10.5a4 4 0 0 0-5.7-.4l-3 3a4 4 0 1 0 5.7 5.7l1.5-1.5"/>'),
  book:    I('<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H19v15H6.5A2.5 2.5 0 0 0 4 20.5Z"/><path d="M4 20.5A2.5 2.5 0 0 1 6.5 18H19v3H6.5A2.5 2.5 0 0 1 4 20.5Z"/>'),
  globe:   I('<circle cx="12" cy="12" r="9"/><path d="M3.5 9h17M3.5 15h17"/><path d="M12 3c-4 5-4 13 0 18 4-5 4-13 0-18Z"/>'),
  brain:   I('<path d="M9.5 4A2.5 2.5 0 0 0 7 6.5 2.5 2.5 0 0 0 5 9a2.5 2.5 0 0 0 1 2 2.5 2.5 0 0 0 1.5 4.5H9.5V4Z"/><path d="M14.5 4A2.5 2.5 0 0 1 17 6.5 2.5 2.5 0 0 1 19 9a2.5 2.5 0 0 1-1 2 2.5 2.5 0 0 1-1.5 4.5H14.5V4Z"/><path d="M12 20v-4"/>'),
  trash:   I('<path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/><path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"/>'),
  logo:    `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <rect x="9" y="3.9" width="12" height="10.9" rx="2.4" stroke="currentColor" stroke-width="1.6"/>
              <path d="M11.7 7.2h6.6M11.7 9.35h6.6M11.7 11.5h6.6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
              <path d="M10.5 14.9 6.4 19" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
              <circle cx="4.7" cy="20.7" r="2.3" fill="currentColor"/>
            </svg>`,
};

/* -------------------------------- toasts --------------------------------- */

export function toast(msg, kind = '') {
  const el = document.createElement('div');
  el.className = 'toast' + (kind ? ` toast--${kind}` : '');
  el.innerHTML = `<span>${esc(msg)}</span>`;
  $('#toasts').appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 250); }, 4200);
}

/* ------------------------------- the store ------------------------------- */

export const S = {
  threads: [],
  activeId: null,
  notes: [],
  links: [],
  pinned: [],
  mesh: { nodes: [], p50: null, online: 0, provider: null },
  mode: 'ask',
  streaming: false,
  abort: null,
  vault: { connected: false, base: null, key: null, folder: 'MeshNet' },
  theme: localStorage.getItem('mesh.theme') || 'dark',
  email: '',
};

const listeners = new Set();
export const subscribe = (fn) => { listeners.add(fn); return () => listeners.delete(fn); };
export const emit = (evt, data) => listeners.forEach(fn => fn(evt, data));

/* ------------------------------ the transport ---------------------------- */

export const token = () => {
  try { return localStorage.getItem(CFG.TOKEN_KEY) || ''; } catch { return ''; }
};

function toLogin() {
  try { localStorage.removeItem(CFG.TOKEN_KEY); } catch {}
  location.href = `${CFG.LOGIN_URL}?next=${encodeURIComponent(location.pathname)}`;
}

/** JSON request. Same 401 behaviour as the web/js/chat/api.js this replaces. */
export async function api(path, init = {}) {
  const headers = { 'Content-Type': 'application/json', ...(init.headers || {}) };
  const t = token();
  if (t) headers.Authorization = 'Bearer ' + t;

  const res = await fetch(CFG.API + path, { ...init, headers });
  if (res.status === 401) { toLogin(); throw new Error('unauthorized'); }

  const ct = res.headers.get('content-type') || '';
  const body = ct.includes('application/json') ? await res.json() : await res.text();
  if (!res.ok) {
    throw new Error((body && body.detail) || (typeof body === 'string' ? body : 'request_failed'));
  }
  return body;
}

/** Raw request — for the SSE turn, where we need the body reader. */
export async function apiRaw(path, init = {}) {
  const headers = { 'Content-Type': 'application/json', ...(init.headers || {}) };
  const t = token();
  if (t) headers.Authorization = 'Bearer ' + t;
  const res = await fetch(CFG.API + path, { ...init, headers });
  if (res.status === 401) { toLogin(); throw new Error('unauthorized'); }
  return res;
}

export function requireAuth() {
  if (!token()) { toLogin(); return false; }
  try {
    S.email = sessionStorage.getItem('nm_email') || localStorage.getItem('nm_email') || '';
  } catch {}
  return true;
}
