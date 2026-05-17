// NeuralMesh chat — sidebar with named agent set (v0.3)
import { store } from './store.js';
import { api } from './api.js';

const NAMED_AGENTS = [
  'Design Agent',
  'Content Agent',
  'Cowork Agent',
  'Email Agent',
  'Sales Agent',
  'Marketing Agent',
  'Personal Assistant Agent',
];

function relTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const ms = Date.now() - d.getTime();
  const s = Math.round(ms / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return Math.floor(s/60) + 'm';
  if (s < 86400) return Math.floor(s/3600) + 'h';
  return Math.floor(s/86400) + 'd';
}
function initials(title) {
  const t = (title || '?').trim();
  // Use the first two initials if title has multiple words
  const parts = t.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return t.slice(0,1).toUpperCase();
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}

function namedIndex(title){
  const i = NAMED_AGENTS.indexOf((title||'').trim());
  return i === -1 ? 999 : i;
}

// Make sure the named agents exist; rename old 'New chat' / 'Untitled' rows to fill slots.
async function ensureNamedAgents() {
  const state = store.get();
  const current = state.agents.slice();
  const titles = new Set(current.map(a => (a.title || '').trim()));
  // Candidates to repurpose: agents named 'New chat' / 'Untitled' / empty
  const reusable = current.filter(a => {
    const t = (a.title || '').trim();
    return !t || t === 'New chat' || t === 'Untitled';
  });

  for (const target of NAMED_AGENTS) {
    if (titles.has(target)) continue;
    try {
      if (reusable.length) {
        const r = reusable.shift();
        const updated = await api.renameAgent(r.id, target);
        store.upsertAgent(updated || Object.assign({}, r, { title: target }));
      } else {
        const a = await api.createAgent(target);
        store.upsertAgent(Object.assign({ unread: 0 }, a));
      }
      titles.add(target);
    } catch (e) {
      console.warn('seed/rename failed for ' + target, e);
    }
  }
}

export function mountSidebar(root) {
  root.innerHTML = '' +
    '<div class="sidebar-header">' +
      '<div class="brand">' +
        '<img src="https://meshnet.co/logo-new.png?v=2" alt="" class="nm-sidebar__logo">' +
        '<span>NeuralMesh</span>' +
      '</div>' +
      '<button class="btn-new-agent" id="btn-new-agent" title="New chat">+ New</button>' +
    '</div>' +
    '<div class="sidebar-search"><input id="sidebar-search-input" type="text" placeholder="Search agents…" /></div>' +
    '<div class="agent-list" id="agent-list"></div>';

  const listEl = root.querySelector('#agent-list');
  const searchEl = root.querySelector('#sidebar-search-input');
  const newBtn = root.querySelector('#btn-new-agent');
  let filter = '';
  let seeded = false;

  searchEl.addEventListener('input', () => {
    filter = searchEl.value.toLowerCase();
    render(store.get());
  });

  newBtn.addEventListener('click', async () => {
    try {
      const a = await api.createAgent('New chat');
      store.upsertAgent(Object.assign({}, a, { unread: 0 }));
      store.setActive(a.id);
    } catch (e) {
      console.error('createAgent failed', e);
      alert('Could not create agent: ' + e.message);
    }
  });

  function render(state) {
    // Sort: named first in fixed order, then the rest by last_message_at desc
    const sorted = state.agents.slice().sort((a, b) => {
      const ai = namedIndex(a.title), bi = namedIndex(b.title);
      if (ai !== bi) return ai - bi;
      const ta = a.last_message_at ? new Date(a.last_message_at).getTime() : 0;
      const tb = b.last_message_at ? new Date(b.last_message_at).getTime() : 0;
      return tb - ta;
    });
    const items = sorted.filter(a => !filter || (a.title || '').toLowerCase().includes(filter));

    if (!items.length) {
      listEl.innerHTML = '<div class="empty-state">No agents yet.<div class="big-new"><button class="btn-new-agent" id="empty-new">+ New agent</button></div></div>';
      const en = listEl.querySelector('#empty-new');
      if (en) en.addEventListener('click', () => newBtn.click());
      return;
    }
    listEl.innerHTML = items.map(a => {
      const active = a.id === state.activeAgentId ? ' active' : '';
      const badge = a.unread > 0 ? '<span class="agent-badge">' + a.unread + '</span>' : '';
      const subtitle = a.last_preview || '';
      return '<div class="agent-row' + active + '" data-id="' + a.id + '">' +
        '<div class="agent-avatar">' + escapeHtml(initials(a.title)) + '</div>' +
        '<div class="agent-meta">' +
          '<div class="agent-title">' + escapeHtml(a.title || 'Untitled') + '</div>' +
          (subtitle ? '<div class="agent-subtitle">' + escapeHtml(subtitle) + '</div>' : '') +
        '</div>' +
        '<div class="agent-right">' +
          '<div class="agent-time">' + relTime(a.last_message_at) + '</div>' +
          badge +
        '</div>' +
      '</div>';
    }).join('');
    listEl.querySelectorAll('.agent-row').forEach(row => {
      row.addEventListener('click', () => store.setActive(row.dataset.id));
    });

    // First time we have data from the backend, ensure the 7 named agents exist
    if (!seeded && state.agents.length >= 0) {
      seeded = true;
      ensureNamedAgents();
    }
  }

  store.subscribe(render);
}
