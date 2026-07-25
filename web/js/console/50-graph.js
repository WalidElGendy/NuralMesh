/* ==========================================================================
   Knowledge graph — the Obsidian model, applied to conversations.

   A note is created for every [[wiki-link]] the assistant or the user writes,
   and for every conversation. Links are bidirectional: opening a note shows
   what links to it (backlinks), which is the thing that makes an Obsidian
   vault compound over time and which no mainstream chat UI has.

   Rendering is a small force simulation on a canvas — no dependency, runs at
   60fps to a few hundred nodes, and stops itself once the layout settles so
   it does not burn battery in a background tab.
   ========================================================================== */

import { S, esc, clamp } from './00-core.js';
import { extractLinks } from './10-markdown.js';

/* --------------------------------- model --------------------------------- */

export const slug = (s) => String(s).trim().toLowerCase().replace(/\s+/g, '-').replace(/[^\p{L}\p{N}-]/gu, '');

export function upsertNote({ title, kind = 'concept', body = '', threadId = null, tags = [] }) {
  const id = slug(title);
  let note = S.notes.find(n => n.id === id);
  if (!note) {
    note = { id, title: title.trim(), kind, body, tags: [...tags], threads: [], created: Date.now(), updated: Date.now() };
    S.notes.push(note);
  } else {
    if (body && body.length > note.body.length) note.body = body;
    note.tags = [...new Set([...note.tags, ...tags])];
    note.updated = Date.now();
  }
  if (threadId && !note.threads.includes(threadId)) note.threads.push(threadId);
  return note;
}

export function link(fromId, toId) {
  if (!fromId || !toId || fromId === toId) return;
  if (!S.links.some(l => l.from === fromId && l.to === toId)) S.links.push({ from: fromId, to: toId });
}

/** Ingest one turn: create the thread note, the concept notes, and the edges. */
export function ingestTurn({ threadId, threadTitle, userText, answerText }) {
  const tNote = upsertNote({ title: threadTitle || 'Untitled thread', kind: 'thread', threadId });
  const combined = `${userText}\n\n${answerText}`;
  const { links, tags } = extractLinks(combined);
  tNote.tags = [...new Set([...tNote.tags, ...tags])];
  tNote.body = String(answerText).slice(0, 1200);

  for (const l of links) {
    const n = upsertNote({ title: l, kind: 'concept', threadId });
    link(tNote.id, n.id);
  }
  // concept-to-concept edges: co-occurrence inside one answer
  for (let i = 0; i < links.length; i++)
    for (let j = i + 1; j < links.length; j++)
      link(slug(links[i]), slug(links[j]));

  return tNote;
}

export const backlinks = (id) => S.links.filter(l => l.to === id).map(l => S.notes.find(n => n.id === l.from)).filter(Boolean);
export const forwardlinks = (id) => S.links.filter(l => l.from === id).map(l => S.notes.find(n => n.id === l.to)).filter(Boolean);

/* ------------------------------ persistence ------------------------------ */

const LS = 'mesh.graph.v1';

export function saveGraph() {
  try {
    localStorage.setItem(LS, JSON.stringify({ notes: S.notes, links: S.links }));
  } catch (e) {
    console.warn('[mesh] graph save failed', e);
  }
}

export function loadGraph() {
  try {
    const raw = JSON.parse(localStorage.getItem(LS) || 'null');
    if (raw?.notes) { S.notes = raw.notes; S.links = raw.links || []; }
  } catch { /* corrupt payload — start clean rather than crash the console */ }
}

/* ------------------------------- retrieval -------------------------------- */

const STOP = new Set(('the a an and or of to in for on with is are was were be been it this that '
  + 'من الى على في عن هذا هذه التي الذي و ما هل').split(/\s+/));

const terms = (q) => String(q).toLowerCase()
  .split(/[^\p{L}\p{N}]+/u)
  .filter(w => w.length > 2 && !STOP.has(w));

/**
 * Keyword recall over the local graph.
 *
 * Scores title matches above body matches, and recency above staleness. This
 * is deliberately simple and local: note text never leaves the browser until
 * a passage is selected as context for a turn.
 */
export function searchNotes(query, limit = 6) {
  const qs = terms(query);
  if (!qs.length || !S.notes.length) return [];
  const now = Date.now();

  return S.notes
    .map(n => {
      const title = n.title.toLowerCase();
      const body = String(n.body || '').toLowerCase();
      let score = 0;
      for (const t of qs) {
        if (title.includes(t)) score += 3;
        if (body.includes(t)) score += 1;
      }
      if (!score) return null;
      const ageDays = (now - (n.updated || now)) / 86400000;
      score *= 1 / (1 + ageDays / 30);            // gentle recency preference
      score /= Math.sqrt(qs.length);
      return { id: n.id, kind: n.kind, title: n.title, text: n.body || n.title, score };
    })
    .filter(Boolean)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit);
}

/* ------------------------------- rendering ------------------------------- */

const KIND_COLOR = {
  thread:  'var(--series-1)',
  concept: 'var(--series-3)',
  tag:     'var(--series-4)',
  vault:   'var(--series-5)',
};

export class GraphView {
  constructor(canvas, { onSelect } = {}) {
    this.c = canvas;
    this.ctx = canvas.getContext('2d');
    this.onSelect = onSelect;
    this.nodes = []; this.edges = [];
    this.focus = null; this.hover = null;
    this.alpha = 1; this.raf = null;
    this.scale = 1; this.ox = 0; this.oy = 0;
    this._bind();
  }

  _bind() {
    const c = this.c;
    c.addEventListener('pointermove', (e) => {
      const p = this._pt(e);
      const n = this._hit(p);
      if (n !== this.hover) { this.hover = n; c.style.cursor = n ? 'pointer' : 'default'; this.kick(0.02); }
    });
    c.addEventListener('pointerleave', () => { this.hover = null; this.kick(0.02); });
    c.addEventListener('click', (e) => {
      const n = this._hit(this._pt(e));
      if (n) { this.focus = n.id; this.onSelect?.(n.id); this.kick(0.4); }
    });
    c.addEventListener('wheel', (e) => {
      e.preventDefault();
      this.scale = clamp(this.scale * (e.deltaY < 0 ? 1.12 : 0.89), 0.35, 3);
      this.kick(0.05);
    }, { passive: false });
  }

  _pt(e) {
    const r = this.c.getBoundingClientRect();
    return { x: (e.clientX - r.left - this.ox) / this.scale, y: (e.clientY - r.top - this.oy) / this.scale };
  }

  _hit(p) {
    for (const n of this.nodes) {
      const d = Math.hypot(n.x - p.x, n.y - p.y);
      if (d < n.r + 7) return n;
    }
    return null;
  }

  setData(notes, links) {
    const W = this.c.clientWidth || 360, H = this.c.clientHeight || 300;
    const prev = new Map(this.nodes.map(n => [n.id, n]));
    const deg = {};
    links.forEach(l => { deg[l.from] = (deg[l.from] || 0) + 1; deg[l.to] = (deg[l.to] || 0) + 1; });

    this.nodes = notes.map((n, i) => {
      const p = prev.get(n.id);
      const a = (i / Math.max(notes.length, 1)) * Math.PI * 2;
      return {
        id: n.id, label: n.title, kind: n.kind,
        x: p?.x ?? W / 2 + Math.cos(a) * (40 + (i % 5) * 18),
        y: p?.y ?? H / 2 + Math.sin(a) * (40 + (i % 5) * 18),
        vx: 0, vy: 0,
        r: clamp(4 + Math.sqrt(deg[n.id] || 0) * 2.4, 4, 13),
      };
    });
    const idx = new Map(this.nodes.map(n => [n.id, n]));
    this.edges = links.map(l => ({ a: idx.get(l.from), b: idx.get(l.to) })).filter(e => e.a && e.b);
    this.kick(1);
  }

  kick(a = 1) {
    this.alpha = Math.max(this.alpha, a);
    if (!this.raf) this.raf = requestAnimationFrame(() => this._tick());
  }

  _tick() {
    this.raf = null;
    const W = this.c.clientWidth, H = this.c.clientHeight;
    // The pane can be hidden when this first runs; simulating against a
    // zero-width box pins every node to the clamp bound. Wait for layout.
    if (W < 40 || H < 40) { this.raf = requestAnimationFrame(() => this._tick()); return; }
    const dpr = Math.min(devicePixelRatio || 1, 2);
    if (this.c.width !== W * dpr) { this.c.width = W * dpr; this.c.height = H * dpr; }

    if (this.alpha > 0.005) {
      const N = this.nodes;
      // repulsion (naive O(n²); fine below ~400 notes)
      for (let i = 0; i < N.length; i++) {
        for (let j = i + 1; j < N.length; j++) {
          const a = N[i], b = N[j];
          let dx = b.x - a.x, dy = b.y - a.y;
          let d2 = dx * dx + dy * dy || 0.01;
          if (d2 > 62500) continue;
          const f = 900 / d2;
          const d = Math.sqrt(d2);
          const fx = (dx / d) * f, fy = (dy / d) * f;
          a.vx -= fx; a.vy -= fy; b.vx += fx; b.vy += fy;
        }
      }
      // springs
      for (const e of this.edges) {
        const dx = e.b.x - e.a.x, dy = e.b.y - e.a.y;
        const d = Math.hypot(dx, dy) || 0.01;
        const f = (d - 62) * 0.012;
        const fx = (dx / d) * f, fy = (dy / d) * f;
        e.a.vx += fx; e.a.vy += fy; e.b.vx -= fx; e.b.vy -= fy;
      }
      // centring + integrate. Margin leaves room for the label under a node.
      const mx = 46, my = 22;
      for (const n of N) {
        n.vx += (W / 2 - n.x) * 0.006;
        n.vy += (H / 2 - n.y) * 0.006;
        n.vx *= 0.85; n.vy *= 0.85;
        n.x += clamp(n.vx, -8, 8); n.y += clamp(n.vy, -8, 8);
        n.x = clamp(n.x, mx, Math.max(mx + 1, W - mx));
        n.y = clamp(n.y, my, Math.max(my + 1, H - my - 14));
      }
      this.alpha *= 0.94;
    }

    this._draw(dpr);
    if (this.alpha > 0.005) this.raf = requestAnimationFrame(() => this._tick());
  }

  _draw(dpr) {
    const g = this.ctx, W = this.c.clientWidth, H = this.c.clientHeight;
    const css = getComputedStyle(document.documentElement);
    const col = (v) => css.getPropertyValue(v).trim() || '#888';

    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, W, H);
    g.save();
    g.translate(this.ox, this.oy); g.scale(this.scale, this.scale);

    const near = new Set();
    if (this.focus || this.hover) {
      const id = this.hover?.id || this.focus;
      near.add(id);
      this.edges.forEach(e => { if (e.a.id === id) near.add(e.b.id); if (e.b.id === id) near.add(e.a.id); });
    }
    const dim = near.size > 0;

    g.lineWidth = 1;
    for (const e of this.edges) {
      const on = !dim || (near.has(e.a.id) && near.has(e.b.id));
      g.strokeStyle = on ? col('--line-2') : col('--line');
      g.globalAlpha = on ? 0.9 : 0.25;
      g.beginPath(); g.moveTo(e.a.x, e.a.y); g.lineTo(e.b.x, e.b.y); g.stroke();
    }

    g.globalAlpha = 1;
    for (const n of this.nodes) {
      const on = !dim || near.has(n.id);
      g.globalAlpha = on ? 1 : 0.28;
      g.beginPath(); g.arc(n.x, n.y, n.r, 0, Math.PI * 2);
      g.fillStyle = col(KIND_COLOR[n.kind]?.replace('var(', '').replace(')', '') || '--series-3');
      g.fill();
      g.lineWidth = 2; g.strokeStyle = col('--s-0'); g.stroke();

      if (on && (this.scale > 0.75 || n.r > 8 || near.has(n.id))) {
        g.globalAlpha = on ? 0.95 : 0.3;
        g.fillStyle = col('--ink-2');
        g.font = '10px system-ui, -apple-system, sans-serif';
        g.textAlign = 'center';
        const t = n.label.length > 18 ? n.label.slice(0, 17) + '…' : n.label;
        g.fillText(t, n.x, n.y + n.r + 11);
      }
    }
    g.restore();
  }

  destroy() { if (this.raf) cancelAnimationFrame(this.raf); }
}

export function graphLegend() {
  return Object.entries({ thread: 'Conversation', concept: 'Concept', tag: 'Tag', vault: 'Vault note' })
    .map(([k, label]) =>
      `<span class="legend__i"><span class="legend__s" style="background:${KIND_COLOR[k]}"></span>${esc(label)}</span>`)
    .join('');
}
