/* ==========================================================================
   Application wiring: turns, streaming, provenance, events, boot.
   ========================================================================== */

import {
  CFG, S, $, $$, esc, fmt, relTime, dirOf, ICON, toast,
  requireAuth, emit, subscribe,
} from './00-core.js';
import { toBlocks, mdToHtml, extractLinks } from './10-markdown.js';
import { figure, tableElement, tableWorthCharting, tileRow, normalise } from './20-charts.js';
import { MODES } from './30-modes.js';
import { runTurn, meshStatus, costModel, titleFor, threads as threadsApi } from './40-engine.js';
import {
  renderShell, paintThreads, paintAnalysis, paintGraphPane, paintNoteList,
  paintVaultPane, showCanvasTab, emptyState,
} from './60-shell.js';
import {
  GraphView, ingestTurn, upsertNote, backlinks, forwardlinks,
  saveGraph, loadGraph, slug,
} from './50-graph.js';
import {
  loadVaultConfig, connectVault, disconnectVault, searchVault, importVaultGraph,
  saveThreadToVault, appendToDaily, toObsidianMarkdown, downloadMarkdown,
} from './55-vault.js';

/* ---------------------------- pipeline strip ----------------------------- */

const STEP_LABEL = { route: 'route', recall: 'recall', plan: 'plan', ground: 'ground', draft: 'draft', verify: 'verify' };

function pipelineEl(mode) {
  const steps = MODES[mode].steps;
  const el = document.createElement('div');
  el.className = 'pipe';
  el.innerHTML = steps.map(s =>
    `<span class="pipe__step" data-step="${s}" data-state="wait">
       <span class="pipe__dot"></span>${STEP_LABEL[s]}<span class="pipe__ms"></span>
     </span>`).join('') +
    `<span class="pipe__spacer"></span>
     <button class="pipe__toggle" type="button" data-act="trace">trace</button>`;
  return el;
}

function setStep(pipe, name, state, info) {
  const el = pipe.querySelector(`[data-step="${name}"]`);
  if (!el) return;
  el.dataset.state = state;
  if (info?.ms) el.querySelector('.pipe__ms').textContent = ' ' + fmt(info.ms, { ms: true });
}

/* ------------------------------ turn rendering --------------------------- */

function turnEl({ role, text, mode }) {
  const el = document.createElement('article');
  el.className = `turn turn--${role}`;
  el.dataset.role = role;

  if (role === 'user') {
    el.innerHTML = `
      <div class="turn__head"><span class="turn__who">You</span></div>
      <div class="usertext" dir="${dirOf(text)}">${esc(text)}</div>`;
    return el;
  }

  el.innerHTML = `
    <div class="turn__head">
      <span class="turn__who">Mesh</span>
      <span style="color:var(--ink-4)">${esc(MODES[mode].label.toLowerCase())}</span>
    </div>
    <div class="turn__pipe"></div>
    <div class="answer" dir="auto"><span class="cursor"></span></div>
    <div class="turn__figs"></div>
    <div class="turn__cites"></div>
    <div class="prov" hidden></div>`;
  return el;
}

/** Re-render the answer body from accumulated raw text. */
function paintAnswer(el, raw, { streaming, noteIndex }) {
  const answer = el.querySelector('.answer');
  const figs = el.querySelector('.turn__figs');
  const blocks = toBlocks(raw);
  answer.innerHTML = '';
  figs.innerHTML = '';

  for (const b of blocks) {
    if (b.kind === 'md') {
      const d = document.createElement('div');
      d.innerHTML = mdToHtml(b.text, { notes: noteIndex });
      while (d.firstChild) answer.appendChild(d.firstChild);
    } else if (b.kind === 'chart') {
      const f = figure(b.spec, { onPin: pinFigure });
      if (f) answer.appendChild(f);
    } else if (b.kind === 'table') {
      if (!streaming && tableWorthCharting(b.table)) {
        const f = figure(b.table, { onPin: pinFigure });
        if (f) { answer.appendChild(f); continue; }
      }
      answer.appendChild(tableElement(b.table));
    }
  }
  if (streaming) answer.appendChild(Object.assign(document.createElement('span'), { className: 'cursor' }));
}

/** Provenance row: the thing only a mesh product can show. */
function paintProvenance(el, { meta, review, sources, memory, timings, onRegen, onCopy, onSave }) {
  const prov = el.querySelector('.prov');
  prov.hidden = false;
  const cost = costModel({ tokens: meta.tokens || 0 });
  const conf = review?.confidence;
  const highIssues = (review?.issues || []).filter(i => i.severity === 'high').length;

  const node = meta.node || (meta.fallback ? 'groq fallback' : 'mesh');
  const chips = [
    `<span class="chip chip--mesh" title="Which node served this turn">${ICON.mesh}<b>${esc(node)}</b></span>`,
    meta.ttft != null ? `<span class="chip" title="Time to first token">ttft <b>${fmt(meta.ttft, { ms: true })}</b></span>` : '',
    meta.tps ? `<span class="chip" title="Generation speed"><b>${fmt(meta.tps, { dp: 0 })}</b> tok/s</span>` : '',
    `<span class="chip" title="Completion tokens"><b>${fmt(meta.tokens)}</b> tok</span>`,
    `<span class="chip chip--good" title="Versus ${fmt(CFG.BASELINE_USD_PER_MTOK, { usd: true })}/Mtok centralised">saves <b>${fmt(cost.saved, { usd: true })}</b> · ${fmt(cost.ratio, { dp: 1 })}×</span>`,
    sources?.length ? `<span class="chip" title="Web sources used">${ICON.globe}<b>${sources.length}</b> sources</span>` : '',
    memory?.length ? `<span class="chip" title="Passages recalled from your workspace">${ICON.brain}<b>${memory.length}</b> recalled</span>` : '',
    conf != null
      ? `<span class="chip ${conf >= 0.75 ? 'chip--good' : 'chip--warn'}" title="Self-check confidence${highIssues ? ` · ${highIssues} high-severity issue(s)` : ''}">
           verified <b>${Math.round(conf * 100)}%</b></span>`
      : '',
  ].filter(Boolean).join('');

  prov.innerHTML = chips +
    `<span class="prov__spacer"></span>
     <button class="chip chip--act" data-act="copy">${ICON.copy} copy</button>
     <button class="chip chip--act" data-act="save">${ICON.vault} note</button>
     <button class="chip chip--act" data-act="regen">${ICON.refresh} retry</button>`;

  prov.querySelector('[data-act="copy"]').onclick = onCopy;
  prov.querySelector('[data-act="save"]').onclick = onSave;
  prov.querySelector('[data-act="regen"]').onclick = onRegen;

  // Review issues surface as an inline warning, not a hidden field.
  if (review && !review.ok && review.issues?.length) {
    const warn = document.createElement('div');
    warn.className = 'trace';
    warn.style.borderRadius = '8px';
    warn.innerHTML = `<div><span class="trace__k">Self-check flagged ${review.issues.length}</span>
      <ol>${review.issues.map(i =>
        `<li><span class="tag">${esc(i.kind)}</span> ${esc(i.fix)}${i.quote ? ` <span style="color:var(--ink-4)">— “${esc(i.quote)}”</span>` : ''}</li>`).join('')}</ol></div>`;
    prov.after(warn);
  }
}

function paintCitations(el, sources) {
  const box = el.querySelector('.turn__cites');
  if (!sources?.length) { box.innerHTML = ''; return; }
  box.innerHTML = `<div class="cites">${sources.map(s => `
    <a class="cite" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">
      <span class="cite__n">${s.n}</span>
      <span><span class="cite__t">${esc(s.title)}</span>
      <span class="cite__d"> ${esc(s.site)}${s.date ? ' · ' + esc(s.date) : ''}</span><br />
      <span style="color:var(--ink-3)">${esc(String(s.snippet).slice(0, 160))}</span></span>
    </a>`).join('')}</div>`;
}

function paintTrace(el, { route, plan, timings, memory }) {
  const pipe = el.querySelector('.pipe');
  const btn = pipe?.querySelector('[data-act="trace"]');
  if (!btn) return;
  let open = false, node = null;
  btn.onclick = () => {
    open = !open;
    btn.textContent = open ? 'hide trace' : 'trace';
    if (!open) { node?.remove(); node = null; return; }
    node = document.createElement('div');
    node.className = 'trace';
    node.innerHTML = `
      <div><span class="trace__k">Route</span>
        intent <b>${esc(route?.intent || '—')}</b> · complexity ${route?.complexity ?? '—'} ·
        web ${route?.needs_web ? 'yes' : 'no'} · memory ${route?.needs_memory ? 'yes' : 'no'} ·
        quantitative ${route?.quantitative ? 'yes' : 'no'}</div>
      ${plan?.steps?.length ? `<div><span class="trace__k">Plan</span>
        <ol>${plan.steps.map(s => `<li>${esc(s.q)} <span style="color:var(--ink-4)">— ${esc(s.needs)}</span></li>`).join('')}</ol>
        ${plan.risks?.length ? `<div style="color:var(--ink-3);margin-top:5px">Risks: ${esc(plan.risks.join('; '))}</div>` : ''}</div>` : ''}
      ${memory?.length ? `<div><span class="trace__k">Recalled</span>
        <ol>${memory.map(m => `<li>${esc(String(m.text).slice(0, 140))}…${m.score ? ` <span style="color:var(--ink-4)">(${m.score.toFixed(2)})</span>` : ''}</li>`).join('')}</ol></div>` : ''}
      <div><span class="trace__k">Timings</span>
        ${Object.entries(timings || {}).map(([k, v]) => `${k} ${fmt(v, { ms: true })}`).join(' · ')}</div>`;
    pipe.after(node);
  };
}

/* -------------------------------- pinning -------------------------------- */

function pinFigure(rawSpec) {
  const spec = normalise(rawSpec);
  const el = figure(rawSpec, { pinnable: false });
  if (!el) return;
  S.pinned.push({ title: spec?.title || 'Figure', el, spec: rawSpec });
  paintAnalysis();
  showCanvasTab('analysis');
  toast('Pinned to Analysis', 'ok');
}

/* ------------------------------- send flow ------------------------------- */

let history = [];

async function send(text) {
  if (S.streaming || !text.trim()) return;
  const inner = $('#streamInner');

  // first turn in an empty thread creates the conversation row
  if (!S.activeId) await newThread({ silent: true });

  // the welcome panel is a placeholder, not a turn — retire it on first send
  if (!history.length) inner.innerHTML = '';

  const uEl = turnEl({ role: 'user', text });
  inner.appendChild(uEl);

  const mode = S.mode;
  const aEl = turnEl({ role: 'assistant', text: '', mode });
  const pipe = pipelineEl(mode);
  aEl.querySelector('.turn__pipe').appendChild(pipe);
  inner.appendChild(aEl);
  scrollDown(true);

  S.streaming = true;
  S.abort = new AbortController();
  setSending(true);

  const noteIndex = new Set(S.notes.map(n => n.id));
  let raw = '';
  let paintPending = false;

  const schedulePaint = () => {
    if (paintPending) return;
    paintPending = true;
    requestAnimationFrame(() => {
      paintPending = false;
      paintAnswer(aEl, raw, { streaming: true, noteIndex });
      scrollDown();
    });
  };

  try {
    const res = await runTurn({
      agentId: S.activeId, query: text, mode, signal: S.abort.signal,
      hooks: {
        onStep: (n, st, info) => setStep(pipe, n, st, info),
        onDelta: (d) => { raw += d; schedulePaint(); },
      },
    });

    paintAnswer(aEl, res.text, { streaming: false, noteIndex });
    paintCitations(aEl, res.sources);
    paintTrace(aEl, res);
    paintProvenance(aEl, {
      ...res,
      onCopy: () => { navigator.clipboard.writeText(res.text); toast('Copied', 'ok'); },
      onSave: () => saveAsNote(text, res.text),
      onRegen: () => { aEl.remove(); uEl.remove(); send(text); },
    });

    history.push({ role: 'user', content: text }, { role: 'assistant', content: res.text });

    // Persistence is the server's job now: /turn and /turn/stream insert both
    // rows and write served_by / tokens / latency_ms, which v0.3 left as
    // NULL / 0 / 0 on every message.

    // knowledge graph
    const thread = S.threads.find(t => t.id === S.activeId);
    // The server auto-titles a thread on its first turn and returns the row.
    if (res.agent) {
      Object.assign(thread || {}, res.agent);
      $('#stageTitle').textContent = res.agent.title || 'Thread';
    } else if (thread && (!thread.title || thread.title === 'New thread')) {
      // Buffered fallback path did not return a row — title it ourselves.
      const t = await titleFor(text);
      if (t) {
        thread.title = t;
        $('#stageTitle').textContent = t;
        threadsApi.rename(S.activeId, t).catch(() => {});
      }
    }

    const { tags } = extractLinks(`${text}\n${res.text}`);
    if (thread) { thread.tags = [...new Set([...(thread.tags || []), ...tags])]; thread.n = (thread.n || 0) + 1; thread.updated_at = new Date().toISOString(); }
    ingestTurn({ threadId: S.activeId, threadTitle: thread?.title, userText: text, answerText: res.text });
    saveGraph();
    paintThreads($('#threadSearch').value);
    paintNoteList();
    $('#nNotes').textContent = String(S.notes.length);
    graph?.setData(S.notes, S.links);

    // vault suggestion
    const m = res.text.match(/^SAVE_NOTE:\s*(.+)$/m);
    if (m && S.vault.connected) toast(`Suggested note: ${m[1].trim()} — Vault → Save`, '');

  } catch (e) {
    if (e.name === 'AbortError') {
      paintAnswer(aEl, raw + '\n\n_(stopped)_', { streaming: false, noteIndex });
    } else {
      aEl.querySelector('.answer').innerHTML =
        `<p style="color:var(--critical)">${esc(e.message)}</p>
         <p style="color:var(--ink-3);font-size:13px">The mesh could not complete this turn.
         Retry, or switch to <b>Ask</b> mode which uses a single call.</p>`;
      console.error(e);
    }
  } finally {
    S.streaming = false; S.abort = null; setSending(false);
    scrollDown();
  }
}

function setSending(on) {
  const btn = $('#sendBtn');
  btn.innerHTML = on ? ICON.stop : ICON.send;
  btn.disabled = on ? false : !$('#input').value.trim();
  btn.setAttribute('aria-label', on ? 'Stop' : 'Send');
}

function scrollDown(force) {
  const s = $('#stream');
  const near = s.scrollHeight - s.scrollTop - s.clientHeight < 220;
  if (force || near) s.scrollTop = s.scrollHeight;
}

/* -------------------------------- threads -------------------------------- */

async function newThread({ silent } = {}) {
  let row;
  try {
    row = await threadsApi.create(null);
  } catch (e) {
    toast('Could not create a thread: ' + e.message, 'err');
    throw e;
  }
  S.threads.unshift({ ...row, n: 0, tags: [] });
  S.activeId = row.id;
  history = [];
  $('#streamInner').innerHTML = welcomeHTML();
  $('#stageTitle').textContent = row.title || 'New thread';
  paintThreads();
  if (!silent) $('#input').focus();
  return row.id;
}

async function openThread(id) {
  S.activeId = id;
  const t = S.threads.find(x => x.id === id);
  $('#stageTitle').textContent = t?.title || 'Thread';
  paintThreads($('#threadSearch').value);

  const inner = $('#streamInner');
  inner.innerHTML = '<div class="empty">loading…</div>';

  let messages = [];
  try {
    const r = await threadsApi.messages(id);
    messages = r?.messages || [];
  } catch (e) {
    inner.innerHTML = `<div class="empty">Could not load this thread — ${esc(e.message)}</div>`;
    return;
  }

  history = messages
    .filter(m => m.role === 'user' || m.role === 'assistant')
    .map(m => ({ role: m.role, content: m.content }));

  inner.innerHTML = '';
  const noteIndex = new Set(S.notes.map(n => n.id));
  for (const m of messages) {
    if (m.role === 'user') { inner.appendChild(turnEl({ role: 'user', text: m.content })); continue; }
    if (m.role !== 'assistant') continue;
    const el = turnEl({ role: 'assistant', text: '', mode: m.mode || 'ask' });
    el.querySelector('.turn__pipe').remove();
    // v0.3 stored replies with six leading spaces from an indented system
    // prompt. Trim on read so old threads do not look broken.
    paintAnswer(el, String(m.content).replace(/^[ \t]+/, ''), { streaming: false, noteIndex });
    if (m.tokens || m.latency_ms || m.served_by) {
      paintProvenance(el, {
        meta: { node: m.served_by, tokens: m.tokens, ms: m.latency_ms, model: m.meta?.model },
        onCopy: () => { navigator.clipboard.writeText(m.content); toast('Copied', 'ok'); },
        onSave: () => saveAsNote('', m.content),
        onRegen: () => toast('Retry is available on the newest turn'),
      });
    }
    inner.appendChild(el);
  }
  if (!messages.length) inner.innerHTML = welcomeHTML();
  updateCtxHint();
  scrollDown(true);
}

/* ------------------------------- welcome --------------------------------- */

const STARTERS = [
  { m: 'analyze', t: 'Unit economics of a GPU node', q: 'Model the unit economics of running one RTX 4090 node on MeshNet: power draw, electricity cost at $0.12/kWh, utilisation at 40%, and payout at $0.89 per million tokens. Show the break-even utilisation.' },
  { m: 'research', t: 'Who is actually cheaper right now', q: 'Compare current published per-million-token prices for Llama 3.3 70B across the main inference providers. Cite each price.' },
  { m: 'analyze', t: 'Where the beta is leaking users', q: 'Given a beta with 258 invites issued, 38 waitlist signups and 18 conversations started, work out the funnel conversion at each stage and identify the single biggest drop-off.' },
  { m: 'ask', t: 'Explain the routing', q: 'In plain terms, how does a request get routed to a GPU node on a decentralised inference mesh, and what happens when the node is slow?' },
];

function welcomeHTML() {
  return `
  <div style="display:grid;gap:20px;padding-top:34px">
    <div style="display:grid;gap:8px">
      <div style="display:flex;align-items:center;gap:9px;color:var(--signal)">${ICON.logo}
        <span style="font-family:var(--mono);font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--ink-3)">NeuralMesh console</span></div>
      <h1 style="font-size:26px;font-weight:600;letter-spacing:-.02em">What are we working out?</h1>
      <p style="color:var(--ink-3);font-size:14px;max-width:56ch">
        Answers arrive with their working shown: which node served them, what was
        retrieved, what the self-check flagged. Data renders as charts you can pin.
        Concepts become <code>[[notes]]</code> you can revisit.</p>
    </div>
    <div style="display:grid;gap:8px">
      ${STARTERS.map(s => `
        <button class="thread" data-starter="${esc(s.q)}" data-starter-mode="${s.m}"
                style="border:1px solid var(--line);background:var(--s-1);padding:11px 13px">
          <span style="display:flex;align-items:center;gap:8px">
            <span class="tag">${esc(s.m)}</span>
            <span class="thread__t" style="font-weight:550;color:var(--ink-1)">${esc(s.t)}</span>
          </span>
          <span class="thread__m" style="white-space:normal">${esc(s.q.slice(0, 110))}…</span>
        </button>`).join('')}
    </div>
  </div>`;
}

/* --------------------------------- notes --------------------------------- */

function saveAsNote(question, answer) {
  const title = (question || answer).split('\n')[0].slice(0, 60) || 'Note';
  upsertNote({ title, kind: 'concept', body: answer, threadId: S.activeId });
  saveGraph(); paintNoteList(); graph?.setData(S.notes, S.links);
  $('#nNotes').textContent = String(S.notes.length);
  showCanvasTab('graph');
  toast('Saved to graph', 'ok');
}

function openNote(id) {
  const n = S.notes.find(x => x.id === id);
  const box = $('#graphDetail');
  if (!n || !box) return;
  const bl = backlinks(id), fl = forwardlinks(id);
  box.innerHTML = `
    <div class="card">
      <div class="card__head"><span class="card__title">${esc(n.title)}</span>
        <span class="card__spacer"></span><span class="tag">${esc(n.kind)}</span></div>
      <div class="card__body" style="display:grid;gap:10px;font-size:12.5px">
        ${n.body ? `<div style="color:var(--ink-2)">${mdToHtml(String(n.body).slice(0, 900))}</div>` : ''}
        ${fl.length ? `<div><span class="trace__k">Links to</span>
          <div class="note__f">${fl.map(x => `<button class="tag" data-note="${esc(x.id)}">${esc(x.title)}</button>`).join('')}</div></div>` : ''}
        ${bl.length ? `<div><span class="trace__k">Backlinks (${bl.length})</span>
          <div class="note__f">${bl.map(x => `<button class="tag" data-note="${esc(x.id)}">${esc(x.title)}</button>`).join('')}</div></div>`
          : `<div style="color:var(--ink-4)">No backlinks yet.</div>`}
      </div>
    </div>`;
  box.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

/* --------------------------------- mesh ---------------------------------- */

let meshTimer = null;

async function refreshMesh() {
  const status = await meshStatus();

  if (!status) {
    // No telemetry endpoint deployed. Say so plainly rather than showing a
    // fabricated node count — the whole point of these chips is that they are
    // true.
    S.mesh = { nodes: [], online: 0, p50: null, provider: null };
    $('#meshPillText').textContent = 'telemetry off';
    $('#meshDot').style.background = 'var(--ink-4)';
    $('#paneMesh').innerHTML = `<div class="card"><div class="card__body">${emptyState(
      'mesh', 'No telemetry endpoint',
      'Deploy <code>mesh_status.py</code> and wire <code>/api/mesh/status</code> to see live node latency, throughput and cost here.'
    )}</div></div>`;
    return;
  }

  S.mesh = {
    nodes: status.providers || [],
    online: status.online || 0,
    p50: status.latency_p50_ms ?? null,
    provider: status.fallback?.provider || null,
  };

  const onFallback = !S.mesh.online;
  $('#meshPillText').innerHTML = onFallback
    ? `<b>${esc(status.fallback?.provider || 'fallback')}</b> · ${esc(status.fallback?.model || '')}`
    : `<b>${S.mesh.online}</b> node${S.mesh.online === 1 ? '' : 's'} · ${S.mesh.p50 ? fmt(S.mesh.p50, { ms: true }) : '—'} p50`;
  $('#meshDot').style.background = onFallback ? 'var(--warn)' : 'var(--signal)';

  const totalTok = status.tokens_today || 0;
  const cost = costModel({ tokens: totalTok });

  const pane = document.createElement('div');
  pane.style.display = 'grid';
  pane.style.gap = '14px';

  const card = document.createElement('div');
  card.className = 'card';
  card.innerHTML = `<div class="card__head"><span class="card__title">Network</span>
    <span class="card__spacer"></span><span class="card__sub">live</span></div>`;
  card.appendChild(tileRow([
    { k: 'Nodes online', v: String(S.mesh.online), d: `${status.registered || 0} registered` },
    { k: 'Median latency', v: S.mesh.p50 ? fmt(S.mesh.p50, { ms: true }) : '—', d: 'p50 across nodes' },
    { k: 'Tokens today', v: fmt(totalTok), d: 'served by the mesh' },
    { k: 'Saved today', v: fmt(cost.saved, { usd: true }), d: `vs ${fmt(CFG.BASELINE_USD_PER_MTOK, { usd: true })}/Mtok`, dir: 'up' },
  ]));
  pane.appendChild(card);

  if (onFallback) {
    const note = document.createElement('div');
    note.className = 'card';
    note.innerHTML = `<div class="card__body" style="font-size:12.5px;color:var(--ink-2);display:grid;gap:6px">
      <span class="chip chip--warn" style="justify-self:start">fallback active</span>
      <p>No provider nodes are online, so traffic is served by
         <b>${esc(status.fallback?.provider || 'the fallback provider')}</b>
         (<code>${esc(status.fallback?.model || 'unknown model')}</code>).
         Answers still carry honest provenance — the chip under each one names
         what actually served it.</p></div>`;
    pane.appendChild(note);
  }

  if (S.mesh.nodes.length) {
    const f = figure({
      type: 'hbar', title: 'Tokens served today', x: 'node', y: ['tokens'],
      data: S.mesh.nodes.slice(0, 10).map(n => ({ node: n.node_id || '—', tokens: n.tokens_today || 0 })),
    }, { onPin: pinFigure });
    if (f) pane.appendChild(f);

    const lat = S.mesh.nodes.filter(n => n.latency_p50_ms).slice(0, 10);
    if (lat.length >= 3) {
      const g = figure({
        type: 'hbar', title: 'Latency by node', subtitle: 'p50 / p95, milliseconds', unit: 'ms',
        x: 'node', y: ['p50', 'p95'],
        data: lat.map(n => ({ node: n.node_id || '—', p50: n.latency_p50_ms, p95: n.latency_p95_ms || n.latency_p50_ms })),
      }, { onPin: pinFigure });
      if (g) pane.appendChild(g);
    }
  }

  $('#paneMesh').innerHTML = '';
  $('#paneMesh').appendChild(pane);
}

/* ------------------------------ command palette -------------------------- */

function commands() {
  return [
    { k: 'New thread', run: () => newThread(), kb: '⌘⇧O' },
    ...Object.entries(MODES).map(([id, m]) => ({ k: `Mode: ${m.label}`, run: () => setMode(id) })),
    { k: 'Toggle threads', run: () => togglePane('threads'), kb: '⌘B' },
    { k: 'Toggle canvas', run: () => togglePane('canvas'), kb: '⌘J' },
    { k: 'Canvas: Analysis', run: () => showCanvasTab('analysis') },
    { k: 'Canvas: Knowledge graph', run: () => showCanvasTab('graph') },
    { k: 'Canvas: Mesh telemetry', run: () => { showCanvasTab('mesh'); refreshMesh(); } },
    { k: 'Canvas: Obsidian vault', run: () => showCanvasTab('vault') },
    { k: 'Export thread as Obsidian markdown', run: exportThread },
    { k: 'Toggle theme', run: toggleTheme },
    ...S.threads.slice(0, 8).map(t => ({ k: `Open: ${t.title || 'Untitled'}`, run: () => openThread(t.id) })),
    ...S.notes.slice(0, 10).map(n => ({ k: `Note: ${n.title}`, run: () => { showCanvasTab('graph'); openNote(n.id); } })),
  ];
}

function openPalette() {
  const scrim = $('#scrim'), input = $('#paletteIn'), list = $('#paletteList');
  scrim.hidden = false; input.value = ''; input.focus();
  let sel = 0;
  const paint = () => {
    const q = input.value.toLowerCase();
    const items = commands().filter(c => c.k.toLowerCase().includes(q)).slice(0, 40);
    sel = Math.min(sel, Math.max(items.length - 1, 0));
    list.innerHTML = items.map((c, i) =>
      `<button class="pitem" data-i="${i}" data-sel="${i === sel ? 1 : 0}">${esc(c.k)}
        ${c.kb ? `<kbd class="pitem__k">${c.kb}</kbd>` : ''}</button>`).join('')
      || `<div class="empty">No match</div>`;
    list.querySelectorAll('.pitem').forEach(b =>
      b.onclick = () => { scrim.hidden = true; items[+b.dataset.i].run(); });
    return items;
  };
  let items = paint();
  input.oninput = () => { sel = 0; items = paint(); };
  input.onkeydown = (e) => {
    if (e.key === 'Escape') { scrim.hidden = true; }
    else if (e.key === 'ArrowDown') { sel = Math.min(sel + 1, items.length - 1); paint(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { sel = Math.max(sel - 1, 0); paint(); e.preventDefault(); }
    else if (e.key === 'Enter') { scrim.hidden = true; items[sel]?.run(); e.preventDefault(); }
  };
  scrim.onclick = (e) => { if (e.target === scrim) scrim.hidden = true; };
}

/* -------------------------------- controls ------------------------------- */

function setMode(m) {
  S.mode = m;
  $$('.mode').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.mode === m)));
  $('#modeHint').textContent = MODES[m].hint;
}

const narrow = () => matchMedia('(max-width: 780px)').matches;

function togglePane(which) {
  const app = $('#app');
  app.dataset[which] = app.dataset[which] === 'on' ? 'off' : 'on';
  // As overlays they would stack; only one at a time on a phone.
  if (narrow() && app.dataset[which] === 'on') {
    const other = which === 'threads' ? 'canvas' : 'threads';
    app.dataset[other] = 'off';
    $$(`.rbtn[data-nav="${other}"]`).forEach(b => b.setAttribute('aria-pressed', 'false'));
  }
  $$(`.rbtn[data-nav="${which}"]`).forEach(b => b.setAttribute('aria-pressed', app.dataset[which] === 'on'));
}

function toggleTheme() {
  S.theme = S.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = S.theme;
  localStorage.setItem('mesh.theme', S.theme);
  $('#themeBtn').innerHTML = S.theme === 'dark' ? ICON.moon : ICON.sun;
  graph?.kick(0.1);
}

function exportThread() {
  const t = S.threads.find(x => x.id === S.activeId);
  const md = toObsidianMarkdown({
    title: t?.title || 'MeshNet thread',
    turns: history,
    tags: t?.tags || [],
  });
  downloadMarkdown(t?.title || 'meshnet-thread', md);
  toast('Exported as Obsidian markdown', 'ok');
}

/* --------------------------------- events -------------------------------- */

let graph = null;

function wire() {
  const input = $('#input');

  // composer
  $('#composer').addEventListener('submit', (e) => {
    e.preventDefault();
    if (S.streaming) { S.abort?.abort(); return; }
    const v = input.value.trim();
    if (!v) return;
    input.value = ''; autosize(); setSending(false);
    send(v);
  });
  input.addEventListener('input', () => { autosize(); $('#sendBtn').disabled = !input.value.trim(); updateCtxHint(); });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('#composer').requestSubmit(); }
  });
  const autosize = () => { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 220) + 'px'; input.dir = dirOf(input.value); };

  // modes
  $$('.mode').forEach(b => b.onclick = () => setMode(b.dataset.mode));

  // global click delegation
  document.addEventListener('click', (e) => {
    const t = e.target.closest('[data-thread],[data-starter],[data-note],[data-wiki],[data-unpin],[data-nav],[data-canvas-tab],[data-tab],[data-tag]');
    if (!t) return;
    if (t.dataset.thread) { openThread(t.dataset.thread); if (narrow()) togglePane('threads'); }
    else if (t.dataset.starter) { setMode(t.dataset.starterMode); send(t.dataset.starter); }
    else if (t.dataset.note) { showCanvasTab('graph'); openNote(t.dataset.note); }
    else if (t.dataset.wiki) { const id = slug(t.dataset.wiki); upsertNote({ title: t.dataset.wiki, threadId: S.activeId }); saveGraph(); paintNoteList(); graph?.setData(S.notes, S.links); showCanvasTab('graph'); openNote(id); }
    else if (t.dataset.unpin != null) { S.pinned.splice(+t.dataset.unpin, 1); paintAnalysis(); }
    else if (t.dataset.nav) togglePane(t.dataset.nav);
    else if (t.dataset.canvasTab) { showCanvasTab(t.dataset.canvasTab); if (t.dataset.canvasTab === 'mesh') refreshMesh(); }
    else if (t.dataset.tab) { showCanvasTab(t.dataset.tab); if (t.dataset.tab === 'mesh') refreshMesh(); }
    else if (t.dataset.tag) { $('#threadSearch').value = t.dataset.tag; paintThreads(t.dataset.tag); }
  });

  $('#newBtn').onclick = () => newThread();
  $('#themeBtn').onclick = toggleTheme;
  $('#paletteBtn').onclick = openPalette;
  $('#exportBtn').onclick = exportThread;
  $('#threadSearch').oninput = (e) => paintThreads(e.target.value);

  // vault pane (delegated because the pane re-renders)
  $('#paneVault').addEventListener('click', async (e) => {
    const id = e.target.closest('button')?.id;
    try {
      if (id === 'vaultConnect') {
        await connectVault($('#vaultKey').value.trim(), $('#vaultFolder').value.trim() || 'MeshNet');
        paintVaultPane();
      } else if (id === 'vaultDisconnect') { disconnectVault(); paintVaultPane(); }
      else if (id === 'vaultImport') { await importVaultGraph(); paintNoteList(); graph?.setData(S.notes, S.links); }
      else if (id === 'vaultSave') {
        const t = S.threads.find(x => x.id === S.activeId);
        await saveThreadToVault({ title: t?.title || 'MeshNet thread', turns: history, tags: t?.tags || [] });
      } else if (id === 'vaultDaily') {
        const last = history.filter(h => h.role === 'assistant').at(-1);
        if (last) await appendToDaily(last.content);
      } else if (id === 'vaultExport') exportThread();
    } catch (err) { toast(err.message, 'err'); }
  });
  $('#paneVault').addEventListener('input', async (e) => {
    if (e.target.id !== 'vaultQ') return;
    const hits = await searchVault(e.target.value);
    $('#vaultHits').innerHTML = hits.length
      ? hits.map(h => `<div class="note"><span class="note__t">${esc(h.title)}</span>
          <span class="note__x">${esc(h.text)}</span></div>`).join('')
      : `<div class="empty">No match</div>`;
  });

  // graph pane
  $('#paneGraph').addEventListener('click', (e) => {
    if (e.target.id === 'graphFit') { graph?.setData(S.notes, S.links); }
    if (e.target.id === 'graphImport') importVaultGraph().then(() => { paintNoteList(); graph?.setData(S.notes, S.links); }).catch(err => toast(err.message, 'err'));
  });

  // shortcuts
  document.addEventListener('keydown', (e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === 'k') { e.preventDefault(); openPalette(); }
    else if (mod && e.key.toLowerCase() === 'b') { e.preventDefault(); togglePane('threads'); }
    else if (mod && e.key.toLowerCase() === 'j') { e.preventDefault(); togglePane('canvas'); }
    else if (mod && e.shiftKey && e.key.toLowerCase() === 'o') { e.preventDefault(); newThread(); }
    else if (e.key === 'Escape' && S.streaming) S.abort?.abort();
    else if (e.key === '/' && document.activeElement === document.body) { e.preventDefault(); $('#input').focus(); }
  });

  // Crossing into phone width turns the panes into overlays; two stacked
  // overlays hide the conversation, so collapse them on the transition.
  const mq = matchMedia('(max-width: 780px)');
  const onNarrow = (e) => {
    if (!e.matches) return;
    const app = $('#app');
    app.dataset.threads = 'off'; app.dataset.canvas = 'off';
    $$('.rbtn[data-nav]').forEach(b => b.setAttribute('aria-pressed', 'false'));
  };
  mq.addEventListener ? mq.addEventListener('change', onNarrow) : mq.addListener(onNarrow);

  subscribe((evt, data) => {
    if (evt !== 'canvas-tab') return;
    if (data === 'mesh') refreshMesh();
    // The graph pane has no layout box until it is visible — lay out on show.
    if (data === 'graph') requestAnimationFrame(() => graph?.setData(S.notes, S.links));
  });
}

function updateCtxHint() {
  const n = history.length;
  $('#ctxHint').textContent = n ? `${Math.min(n, CFG.MAX_CONTEXT_TURNS)} turns in context` : '';
}

/* ---------------------------------- boot --------------------------------- */

export async function boot() {
  document.documentElement.dataset.theme = S.theme;
  loadGraph();
  loadVaultConfig();
  renderShell();
  // On a phone the side panes are overlays; start with the conversation clear.
  if (matchMedia('(max-width: 780px)').matches) {
    $('#app').dataset.threads = 'off';
    $('#app').dataset.canvas = 'off';
    $$('.rbtn[data-nav]').forEach(b => b.setAttribute('aria-pressed', 'false'));
  }
  $('#themeBtn').innerHTML = S.theme === 'dark' ? ICON.moon : ICON.sun;
  wire();
  setMode('ask');

  if (!requireAuth()) return;

  try {
    const r = await threadsApi.list();
    const list = Array.isArray(r) ? r : (r?.agents || r?.items || []);
    S.threads = list.map(t => ({ ...t, tags: [], n: 0 }));
  } catch (e) {
    toast('Could not load threads: ' + e.message, 'err');
    S.threads = [];
  }
  paintThreads();

  // graph canvas
  const c = $('#graph');
  if (c) {
    graph = new GraphView(c, { onSelect: openNote });
    requestAnimationFrame(() => graph.setData(S.notes, S.links));
  }
  paintNoteList();
  $('#nNotes').textContent = String(S.notes.length);

  if (S.threads.length) await openThread(S.threads[0].id);
  else $('#streamInner').innerHTML = welcomeHTML();

  refreshMesh();
  meshTimer = setInterval(refreshMesh, 45000);
  $('#input').focus();
}
