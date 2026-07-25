/* ==========================================================================
   Obsidian vault bridge.

   Talks to the "Local REST API" community plugin, which exposes the user's
   vault on 127.0.0.1. Everything stays on the user's own machine: the browser
   calls localhost directly, so no note content ever reaches MeshNet servers.

   Setup, once, per machine:
     1. Obsidian → Settings → Community plugins → install "Local REST API"
     2. Copy the API key it shows
     3. Console → Vault → Connect, paste the key

   Because it is localhost-only, this is a power-user feature. The in-app
   knowledge graph (50-graph.js) is the layer every beta user gets; this
   syncs that graph to a real vault for the people who keep one.
   ========================================================================== */

import { S, toast } from './00-core.js';
import { upsertNote, link, slug, saveGraph } from './50-graph.js';

const LS = 'mesh.vault.v1';
const HOSTS = ['https://127.0.0.1:27124', 'http://127.0.0.1:27123'];

export function loadVaultConfig() {
  try {
    const v = JSON.parse(localStorage.getItem(LS) || 'null');
    if (v?.key) { S.vault = { ...S.vault, ...v }; }
  } catch {}
  return S.vault;
}

function saveVaultConfig() {
  localStorage.setItem(LS, JSON.stringify({
    base: S.vault.base, key: S.vault.key, folder: S.vault.folder, connected: S.vault.connected,
  }));
}

async function call(path, init = {}, base = S.vault.base) {
  const res = await fetch(base + path, {
    ...init,
    headers: {
      authorization: `Bearer ${S.vault.key}`,
      'content-type': init.body && !init.headers?.['content-type'] ? 'text/markdown' : undefined,
      ...(init.headers || {}),
    },
  });
  if (!res.ok) throw new Error(`vault ${res.status}`);
  return res;
}

/** Try both the TLS and plain ports; the plugin defaults to TLS with a self-signed cert. */
export async function connectVault(key, folder = 'MeshNet') {
  S.vault.key = key; S.vault.folder = folder;
  for (const base of HOSTS) {
    try {
      const res = await fetch(base + '/', { headers: { authorization: `Bearer ${key}` } });
      if (res.ok) {
        const info = await res.json().catch(() => ({}));
        S.vault.base = base;
        S.vault.connected = true;
        S.vault.name = info?.versions ? 'Obsidian' : 'vault';
        saveVaultConfig();
        toast(`Vault connected on ${base.replace(/^https?:\/\//, '')}`, 'ok');
        return true;
      }
    } catch { /* next host */ }
  }
  S.vault.connected = false;
  saveVaultConfig();
  throw new Error(
    'Could not reach Obsidian. Check that the Local REST API plugin is enabled, ' +
    'and if you are on https accept the certificate once at https://127.0.0.1:27124'
  );
}

export function disconnectVault() {
  S.vault = { connected: false, base: null, key: null, folder: S.vault.folder };
  saveVaultConfig();
}

/* --------------------------------- read ---------------------------------- */

export async function listVault(dir = '') {
  const res = await call(`/vault/${dir}`, { headers: { accept: 'application/json' } });
  const j = await res.json();
  return j.files || [];
}

export async function readNote(path) {
  const res = await call(`/vault/${encodeURI(path)}`, { headers: { accept: 'text/markdown' } });
  return res.text();
}

export async function searchVault(query, limit = 8) {
  if (!S.vault.connected) return [];
  try {
    const res = await call(`/search/simple/?query=${encodeURIComponent(query)}&contextLength=220`, { method: 'POST' });
    const hits = await res.json();
    return hits.slice(0, limit).map(h => ({
      kind: 'vault',
      title: h.filename.replace(/\.md$/, '').split('/').pop(),
      path: h.filename,
      text: (h.matches || []).map(m => m.context).join(' … ').slice(0, 800),
      score: h.score,
    }));
  } catch { return []; }
}

/* --------------------------------- write --------------------------------- */

const fm = (o) => '---\n' + Object.entries(o)
  .map(([k, v]) => `${k}: ${Array.isArray(v) ? '[' + v.join(', ') + ']' : v}`).join('\n') + '\n---\n\n';

/** Write one conversation into the vault as a proper Obsidian note. */
export async function saveThreadToVault({ title, turns, tags = [], sources = [] }) {
  if (!S.vault.connected) throw new Error('vault not connected');
  const safe = String(title).replace(/[\\/:*?"<>|]/g, '-').slice(0, 80) || 'MeshNet note';
  const path = `${S.vault.folder}/${safe}.md`;

  const body =
    fm({
      title: safe,
      source: 'NeuralMesh',
      created: new Date().toISOString().slice(0, 10),
      tags: ['meshnet', ...tags],
    }) +
    turns.map(t => t.role === 'user'
      ? `## ${t.content.split('\n')[0].slice(0, 120)}\n`
      : `${t.content}\n`
    ).join('\n') +
    (sources.length
      ? '\n\n## Sources\n' + sources.map(s => `${s.n}. [${s.title}](${s.url})`).join('\n')
      : '');

  await call(`/vault/${encodeURI(path)}`, { method: 'PUT', body });
  toast(`Saved to vault → ${path}`, 'ok');
  return path;
}

/** Append a single answer to today's daily note. */
export async function appendToDaily(text) {
  if (!S.vault.connected) throw new Error('vault not connected');
  await call('/periodic/daily/', { method: 'POST', body: `\n\n${text}\n` });
  toast('Appended to daily note', 'ok');
}

/* --------------------------------- import -------------------------------- */

/** Pull vault notes into the in-app graph so retrieval can see them. */
export async function importVaultGraph({ limit = 400 } = {}) {
  if (!S.vault.connected) throw new Error('vault not connected');
  const files = (await listVault('')).filter(f => f.endsWith('.md')).slice(0, limit);
  let n = 0;
  for (const f of files) {
    let body = '';
    try { body = await readNote(f); } catch { continue; }
    const title = f.replace(/\.md$/, '').split('/').pop();
    const note = upsertNote({ title, kind: 'vault', body: body.slice(0, 1500) });
    note.path = f;
    for (const m of body.matchAll(/\[\[([^\]|]+)(?:\|[^\]]+)?\]\]/g)) {
      const t = m[1].trim();
      upsertNote({ title: t, kind: 'vault' });
      link(slug(title), slug(t));
    }
    n++;
  }
  saveGraph();
  toast(`Imported ${n} vault notes`, 'ok');
  return n;
}

/* ------------------------------ markdown out ----------------------------- */

/** Obsidian-flavoured markdown export — works with no plugin at all. */
export function toObsidianMarkdown({ title, turns, tags = [], sources = [] }) {
  return fm({
    title, source: 'NeuralMesh', created: new Date().toISOString().slice(0, 10),
    tags: ['meshnet', ...tags],
  }) + turns.map(t =>
    t.role === 'user' ? `> [!question] ${t.content}\n` : `${t.content}\n`
  ).join('\n') + (sources.length
    ? '\n## Sources\n' + sources.map(s => `${s.n}. [${s.title}](${s.url})`).join('\n') : '');
}

export function downloadMarkdown(name, text) {
  const blob = new Blob([text], { type: 'text/markdown' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${String(name).replace(/[\\/:*?"<>|]/g, '-').slice(0, 80)}.md`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
