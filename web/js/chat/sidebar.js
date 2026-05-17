// NeuralMesh chat — sidebar with agent list, search, +New (v0.1)
import { store } from './store.js';
import { api } from './api.js';

function relTime(iso) {
  if (!iso) return '';
  const d = new Date(iso); const ms = Date.now() - d.getTime();
  const s = Math.round(ms / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return Math.floor(s/60) + 'm';
  if (s < 86400) return Math.floor(s/3600) + 'h';
  return Math.floor(s/86400) + 'd';
}

function initials(title) {
  const t = (title || '?').trim();
  return t.slice(0,1).toUpperCase();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}

export function mountSidebar(root) {
  root.innerHTML = ''
    + '<div class="sidebar-header">'
    +   '<div class="brand">NeuralMesh</div>'
    +   '<button class="btn-new-agent" id="btn-new-agent">+ New</button>'
    + '</div>'
    + '<div class="sidebar-search"><input id="sidebar-search-input" type="text" placeholder="Search agents…" /></div>'
    + '<div class="agent-list" id="agent-list"></div>';
  const listEl = root.querySelector('#agent-list');
  const searchEl = root.querySelector('#sidebar-search-input');
  const newBtn = root.querySelector('#btn-new-agent');
  let filter = '';
  searchEl.addEventListener('input', () => { filter = searchEl.value.toLowerCase(); render(store.get()); });
  newBtn.addEventListener('click', async () => {
    try {
      const a = await api.createAgent('New chat');
      store.upsertAgent(Object.assign({}, a, { unread: 0 }));
      store.setActive(a.id);
    } catch (e) { console.error('createAgent failed', e); alert('Could not create agent: ' + e.message); }
  });

  function render(state) {
    const items = state.agents.filter(a => !filter || (a.title || '').toLowerCase().includes(filter));
    if (!items.length) {
      listEl.innerHTML = '<div class="empty-state">No agents yet.<div class="big-new"><button class="btn-new-agent" id="empty-new">+ New agent</button></div></div>';
      const en = listEl.querySelector('#empty-new'); if (en) en.addEventListener('click', () => newBtn.click());
      return;
    }
    listEl.innerHTML = items.map(a => {
      const active = a.id === state.activeAgentId ? ' active' : '';
      const badge = a.unread > 0 ? '<span class="agent-badge">' + a.unread + '</span>' : '';
      return '<div class="agent-row' + active + '" data-id="' + a.id + '">'
        + '<div class="agent-avatar">' + initials(a.title) + '</div>'
        + '<div class="agent-meta">'
        +   '<div class="agent-title">' + escapeHtml(a.title || 'Untitled') + '</div>'
        +   '<div class="agent-subtitle">' + escapeHtml(a.last_preview || '') + '</div>'
        + '</div>'
        + '<div class="agent-right">'
        +   '<div class="agent-time">' + relTime(a.last_message_at) + '</div>'
        +   badge
        + '</div>'
        + '</div>';
    }).join('');
    listEl.querySelectorAll('.agent-row').forEach(row => {
      row.addEventListener('click', () => store.setActive(row.dataset.id));
    });
  }
  store.subscribe(render);
}
