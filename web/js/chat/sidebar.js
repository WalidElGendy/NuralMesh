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

const AGENT_ICONS = {
  'Design Agent': '<svg class="nm-agent-mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><circle cx="7.5" cy="10.5" r="1" fill="currentColor"/><circle cx="12" cy="7.5" r="1" fill="currentColor"/><circle cx="16.5" cy="10.5" r="1" fill="currentColor"/><circle cx="15.5" cy="15" r="1" fill="currentColor"/><path d="M12 21c-1.5 0-2-1-1.5-2 .5-1 .5-2-.5-2.5-1-.5-2 0-3 0"/></svg>',
  'Content Agent': '<svg class="nm-agent-mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20l4-1 11-11-3-3L5 16l-1 4z"/><path d="M14 6l3 3"/></svg>',
  'Cowork Agent': '<svg class="nm-agent-mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="9" cy="8" r="3"/><path d="M3 20c0-3 3-5 6-5s6 2 6 5"/><circle cx="17" cy="9" r="2.3"/><path d="M15 14.2c2.5 0 6 1.6 6 4.3"/></svg>',
  'Email Agent': '<svg class="nm-agent-mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/></svg>',
  'Sales Agent': '<svg class="nm-agent-mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 17l5-5 4 4 8-9"/><path d="M14 7h6v6"/></svg>',
  'Marketing Agent': '<svg class="nm-agent-mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 10v4l11 5V5L3 10z"/><path d="M14 8c2 1 2 7 0 8"/><path d="M7 14v3a2 2 0 0 0 4 0v-1"/></svg>',
  'Personal Assistant Agent': '<svg class="nm-agent-mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5L12 3z"/><path d="M19 14l.7 2.3L22 17l-2.3.7L19 20l-.7-2.3L16 17l2.3-.7L19 14z"/></svg>'
};
function iconForAgent(title){ return AGENT_ICONS[(title||'').trim()] || '<svg class="nm-agent-mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><circle cx="7.5" cy="10.5" r="1" fill="currentColor"/><circle cx="12" cy="7.5" r="1" fill="currentColor"/><circle cx="16.5" cy="10.5" r="1" fill="currentColor"/><circle cx="15.5" cy="15" r="1" fill="currentColor"/><path d="M12 21c-1.5 0-2-1-1.5-2 .5-1 .5-2-.5-2.5-1-.5-2 0-3 0"/></svg>'; }


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
    const items = sorted.filter(a => NAMED_AGENTS.indexOf((a.title||'').trim()) !== -1).filter(a => !filter || (a.title || '').toLowerCase().includes(filter));

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
        '<div class="agent-avatar">' + iconForAgent(a.title) + '</div>' +
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
