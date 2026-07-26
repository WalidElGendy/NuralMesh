/* ==========================================================================
   Shell — rail, threads, stage, canvas.

   The agent sidebar is gone. It listed agents that did not function, and the
   personas behind it were actively degrading answers (see 30-modes.js and mesh_prompts.py).
   In its place: threads on the left, and an analyst CANVAS on the right that
   holds pinned figures, the knowledge graph, live mesh telemetry, and the
   vault bridge.
   ========================================================================== */

import { $, $$, S, CFG, ICON, esc, relTime, emit } from './00-core.js';
import { MODES } from './30-modes.js';
import { graphLegend } from './50-graph.js';

export function renderShell() {
  $('#app').innerHTML = `
  <!-- ------------------------------ appbar ---------------------------- -->
  <header class="appbar">
    <a class="appbar__brand" href="/" title="NeuralMesh">
      <span class="appbar__logo" role="img" aria-label="neo."></span>
    </a>
    <span class="appbar__tag">Console</span>
    <span class="appbar__spacer"></span>
    <div class="appbar__user" id="authUser" hidden>
      <span class="appbar__avatar" id="authAvatar" aria-hidden="true"></span>
      <span class="appbar__name" id="authName"></span>
    </div>
    <button class="authbtn" id="signOutBtn" type="button" hidden>Sign out</button>
    <a class="authbtn authbtn--primary" id="signInBtn" href="${CFG.LOGIN_URL}" hidden>Sign in</a>
  </header>

  <!-- ------------------------------ rail ------------------------------ -->
  <nav class="rail" aria-label="Sections">
    <a class="rail__mark" href="/" title="NeuralMesh" style="color:var(--signal)">${ICON.logo}</a>
    <button class="rbtn" data-nav="threads" aria-pressed="true" title="Threads  ⌘B">${ICON.chat}</button>
    <button class="rbtn" data-canvas-tab="analysis" title="Analysis">${ICON.chart}</button>
    <button class="rbtn" data-canvas-tab="graph" title="Knowledge graph">${ICON.graph}</button>
    <button class="rbtn" data-canvas-tab="mesh" title="Mesh telemetry">${ICON.mesh}<span class="rbtn__dot" id="meshDot"></span></button>
    <button class="rbtn" data-canvas-tab="vault" title="Obsidian vault">${ICON.vault}</button>
    <div class="rail__spacer"></div>
    <button class="rbtn" id="themeBtn" title="Theme">${ICON.moon}</button>
    <button class="rbtn" id="paletteBtn" title="Command palette  ⌘K">${ICON.search}</button>
  </nav>

  <!-- ----------------------------- threads ---------------------------- -->
  <aside class="threads" aria-label="Threads">
    <div class="threads__head">
      <div class="threads__title"><span>Threads</span><span id="threadCount"></span></div>
      <button class="newbtn" id="newBtn">${ICON.plus}<span>New thread</span><kbd>⌘⇧O</kbd></button>
      <label class="search">${ICON.search}<input id="threadSearch" type="search" autocomplete="off" placeholder="Filter threads" aria-label="Filter threads" /></label>
    </div>
    <div class="threads__list" id="threadList"></div>
  </aside>

  <!-- ------------------------------ stage ----------------------------- -->
  <main class="stage">
    <header class="topbar">
      <button class="iconbtn" data-nav="threads" title="Toggle threads  ⌘B">${ICON.panelL}</button>
      <span class="topbar__title" id="stageTitle">New thread</span>
      <span class="topbar__spacer"></span>
      <span class="meshpill" id="meshPill" title="Live mesh status">
        <span class="pulse"></span><span id="meshPillText">connecting…</span>
      </span>
      <button class="iconbtn" id="exportBtn" title="Export to Obsidian markdown">${ICON.book}</button>
      <button class="iconbtn" data-nav="canvas" title="Toggle canvas  ⌘J">${ICON.panelR}</button>
    </header>

    <div class="stream" id="stream" tabindex="-1">
      <div class="stream__inner" id="streamInner"></div>
    </div>

    <div class="composer-wrap">
      <form class="composer" id="composer">
        <div class="composer__modes" role="group" aria-label="Answer mode">
          ${Object.entries(MODES).map(([k, m]) => `
            <button type="button" class="mode" data-mode="${k}" aria-pressed="${k === 'ask'}"
                    title="${esc(m.hint)}">${ICON[m.icon]}<span>${m.label}</span></button>`).join('')}
          <span class="composer__spacer"></span>
          <span class="chip" id="modeHint">${esc(MODES.ask.hint)}</span>
        </div>
        <div class="composer__body">
          <textarea id="input" rows="1" placeholder="Ask the mesh…  ⌘K for commands"
                    aria-label="Message" autocomplete="off"></textarea>
          <button class="sendbtn" id="sendBtn" type="submit" disabled aria-label="Send">${ICON.send}</button>
        </div>
        <div class="composer__hint">
          <span><kbd>↵</kbd> send</span><span><kbd>⇧↵</kbd> newline</span>
          <span class="composer__spacer"></span>
          <span id="ctxHint"></span>
        </div>
      </form>
    </div>
  </main>

  <!-- ------------------------------ canvas ---------------------------- -->
  <aside class="canvas" aria-label="Canvas">
    <div class="canvas__tabs" role="tablist">
      <button class="ctab" role="tab" data-tab="analysis" aria-selected="true">${ICON.chart}<span>Analysis</span><span class="ctab__n" id="nPinned">0</span></button>
      <button class="ctab" role="tab" data-tab="graph"  aria-selected="false">${ICON.graph}<span>Graph</span><span class="ctab__n" id="nNotes">0</span></button>
      <button class="ctab" role="tab" data-tab="mesh"   aria-selected="false">${ICON.mesh}<span>Mesh</span></button>
      <button class="ctab" role="tab" data-tab="vault"  aria-selected="false">${ICON.vault}<span>Vault</span></button>
    </div>

    <div class="canvas__body">
      <section class="canvas__pane" data-pane="analysis" id="paneAnalysis"></section>
      <section class="canvas__pane" data-pane="graph" id="paneGraph" hidden></section>
      <section class="canvas__pane" data-pane="mesh" id="paneMesh" hidden></section>
      <section class="canvas__pane" data-pane="vault" id="paneVault" hidden></section>
    </div>
  </aside>`;

  paintAuth();
  paintAnalysis();
  paintGraphPane();
  paintVaultPane();
}

/* ---------------------------------- auth ---------------------------------- */

/** The app bar identity block. S.email is filled in by requireAuth(). */
export function paintAuth() {
  const email = S.email || '';
  const on = !!email;
  $('#authUser').hidden = !on;
  $('#signOutBtn').hidden = !on;
  $('#signInBtn').hidden = on;
  if (!on) return;
  $('#authName').textContent = email;
  $('#authName').title = email;
  $('#authAvatar').textContent = email.slice(0, 1);
}

/** Same contract as account.html: drop the server session, then the bearer. */
export async function signOut() {
  try { await fetch(CFG.API + '/auth/logout', { method: 'POST' }); } catch {}
  try { localStorage.removeItem(CFG.TOKEN_KEY); } catch {}
  location.href = CFG.LOGIN_URL;
}

/* ------------------------------ empty states ----------------------------- */

export const emptyState = (icon, title, note) => `
  <div class="empty">${ICON[icon]}<strong style="color:var(--ink-2);font-weight:550">${esc(title)}</strong>
  <span>${note}</span></div>`;

/* --------------------------------- threads ------------------------------- */

export function paintThreads(filter = '') {
  const list = $('#threadList');
  const f = filter.trim().toLowerCase();
  const items = S.threads.filter(t => !f || (t.title || '').toLowerCase().includes(f));
  $('#threadCount').textContent = String(S.threads.length || '');

  if (!items.length) {
    list.innerHTML = emptyState('chat', f ? 'No match' : 'No threads yet',
      f ? 'Try a different filter.' : 'Ask something to start one.');
    return;
  }

  const groups = { Today: [], 'This week': [], Earlier: [] };
  const now = Date.now();
  for (const t of items) {
    const age = (now - new Date(t.updated_at || t.created_at).getTime()) / 86400000;
    (age < 1 ? groups.Today : age < 7 ? groups['This week'] : groups.Earlier).push(t);
  }

  list.innerHTML = Object.entries(groups).filter(([, v]) => v.length).map(([k, v]) => `
    <div class="threads__group">${k}</div>
    ${v.map(t => `
      <button class="thread" data-thread="${esc(t.id)}" aria-current="${t.id === S.activeId}">
        <span class="thread__t">${esc(t.title || 'Untitled')}</span>
        <span class="thread__m">
          <span>${relTime(t.updated_at || t.created_at)}</span>
          ${t.n ? `<span>· ${t.n} turns</span>` : ''}
          ${t.mode && t.mode !== 'ask' ? `<span>· ${esc(t.mode)}</span>` : ''}
        </span>
        ${t.tags?.length ? `<span class="thread__tags">${t.tags.slice(0, 3).map(x => `<span class="tag">#${esc(x)}</span>`).join('')}</span>` : ''}
      </button>`).join('')}
  `).join('');
}

/* -------------------------------- analysis ------------------------------- */

export function paintAnalysis() {
  const pane = $('#paneAnalysis');
  $('#nPinned').textContent = String(S.pinned.length);
  if (!S.pinned.length) {
    pane.innerHTML = emptyState('chart', 'Nothing pinned',
      'Charts in an answer have a <b>pin</b> action. Pinned figures collect here so you can compare across threads.');
    return;
  }
  pane.innerHTML = '';
  S.pinned.forEach((p, i) => {
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `<div class="card__head">
        <span class="card__title">${esc(p.title || 'Figure ' + (i + 1))}</span>
        <span class="card__spacer"></span>
        <button class="tablebtn" data-unpin="${i}">remove</button>
      </div><div class="card__body"></div>`;
    card.querySelector('.card__body').appendChild(p.el);
    pane.appendChild(card);
  });
}

/* ---------------------------------- graph -------------------------------- */

export function paintGraphPane() {
  $('#nNotes').textContent = String(S.notes.length);
  const pane = $('#paneGraph');
  if (pane.dataset.built === '1') { $('#graphNoteList') && paintNoteList(); return; }
  pane.dataset.built = '1';
  pane.innerHTML = `
    <div class="graphwrap">
      <canvas id="graph" height="300" aria-label="Knowledge graph"></canvas>
      <div class="graph__ctl">
        <button class="tablebtn" id="graphFit">fit</button>
        <button class="tablebtn" id="graphImport">import vault</button>
      </div>
      <div class="graph__legend">${graphLegend()}</div>
    </div>
    <div id="graphDetail"></div>
    <div class="card">
      <div class="card__head"><span class="card__title">Notes</span><span class="card__spacer"></span>
        <span class="card__sub" id="graphCount"></span></div>
      <div class="card__body" id="graphNoteList" style="display:grid;gap:8px"></div>
    </div>`;
  paintNoteList();
}

export function paintNoteList() {
  const el = $('#graphNoteList'); if (!el) return;
  $('#graphCount') && ($('#graphCount').textContent = `${S.notes.length} · ${S.links.length} links`);
  if (!S.notes.length) { el.innerHTML = emptyState('graph', 'Empty graph', 'Notes appear as answers create <code>[[links]]</code>.'); return; }
  el.innerHTML = [...S.notes].sort((a, b) => b.updated - a.updated).slice(0, 40).map(n => `
    <div class="note" data-note="${esc(n.id)}">
      <span class="note__t">${esc(n.title)}</span>
      ${n.body ? `<span class="note__x">${esc(String(n.body).replace(/[#*`>]/g, '').slice(0, 180))}</span>` : ''}
      <span class="note__f">
        <span class="tag">${esc(n.kind)}</span>
        ${n.tags.slice(0, 3).map(t => `<span class="tag">#${esc(t)}</span>`).join('')}
        <span class="card__sub" style="margin-inline-start:auto">${relTime(new Date(n.updated).toISOString())}</span>
      </span>
    </div>`).join('');
}

/* ---------------------------------- vault -------------------------------- */

export function paintVaultPane() {
  const pane = $('#paneVault');
  const v = S.vault;
  pane.innerHTML = v.connected ? `
    <div class="card">
      <div class="card__head"><span class="card__title">Obsidian</span><span class="card__spacer"></span>
        <span class="chip chip--good">connected</span></div>
      <div class="card__body" style="display:grid;gap:9px">
        <div class="card__sub">${esc(v.base)} · folder <b>${esc(v.folder)}</b></div>
        <button class="newbtn" id="vaultSave">${ICON.down}<span>Save this thread to vault</span></button>
        <button class="newbtn" id="vaultDaily">${ICON.plus}<span>Append last answer to daily note</span></button>
        <button class="newbtn" id="vaultImport">${ICON.refresh}<span>Import vault into graph</span></button>
        <button class="tablebtn" id="vaultDisconnect" style="justify-self:start">disconnect</button>
      </div>
    </div>
    <div class="card">
      <div class="card__head"><span class="card__title">Vault search</span></div>
      <div class="card__body" style="display:grid;gap:9px">
        <label class="search">${ICON.search}<input id="vaultQ" placeholder="Search notes" /></label>
        <div id="vaultHits" style="display:grid;gap:8px"></div>
      </div>
    </div>` : `
    <div class="card">
      <div class="card__head"><span class="card__title">Connect Obsidian</span></div>
      <div class="card__body" style="display:grid;gap:10px;font-size:12.5px;color:var(--ink-2)">
        <p>Your vault stays on your machine. The browser talks to Obsidian on
           <code>127.0.0.1</code> directly — note content never reaches MeshNet servers.</p>
        <ol style="padding-inline-start:18px;display:grid;gap:4px">
          <li>Obsidian → Settings → Community plugins → install <b>Local REST API</b></li>
          <li>Enable it and copy the API key</li>
          <li>Paste it below</li>
        </ol>
        <label class="search">${ICON.link}<input id="vaultKey" type="password" placeholder="API key" /></label>
        <label class="search">${ICON.vault}<input id="vaultFolder" value="MeshNet" placeholder="Target folder" /></label>
        <button class="newbtn" id="vaultConnect">${ICON.vault}<span>Connect vault</span></button>
        <p style="color:var(--ink-4)">On https you may need to accept the plugin's self-signed
           certificate once at <code>https://127.0.0.1:27124</code>.</p>
      </div>
    </div>
    <div class="card">
      <div class="card__head"><span class="card__title">No vault?</span></div>
      <div class="card__body" style="display:grid;gap:9px;font-size:12.5px;color:var(--ink-2)">
        <p>Every thread still exports as Obsidian-flavoured markdown — frontmatter,
           tags and <code>[[links]]</code> intact.</p>
        <button class="newbtn" id="vaultExport">${ICON.book}<span>Export this thread</span></button>
      </div>
    </div>`;
}

/* ---------------------------------- mesh --------------------------------- */

export function paintMeshPane(html) { $('#paneMesh').innerHTML = html; }

/* -------------------------------- switching ------------------------------ */

export function showCanvasTab(tab) {
  $$('.ctab').forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === tab)));
  $$('.canvas__pane').forEach(p => { p.hidden = p.dataset.pane !== tab; });
  $$('.rbtn[data-canvas-tab]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.canvasTab === tab)));
  $('#app').dataset.canvas = 'on';
  emit('canvas-tab', tab);
}
