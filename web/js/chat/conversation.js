// NeuralMesh chat — conversation pane: header + messages (v0.2)
import { store } from './store.js';
import { api } from './api.js';

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, function(c) {
    return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c];
  });
}
function initials(s){ const t=(s||'?').trim(); return t.slice(0,1).toUpperCase(); }

export function mountConversation(headerEl, messagesEl) {
  let lastAgentId = null;

  async function loadMessages(agentId) {
    if (!agentId) return;
    try {
      const list = await api.getMessages(agentId);
      store.setMessages(agentId, Array.isArray(list) ? list : (list && list.messages) || []);
    } catch (e) { console.error('getMessages failed', e); }
  }

  function renderHeader(state) {
    const a = state.agents.find(x => x.id === state.activeAgentId);
    const titleEl = document.getElementById('pane-title');
    const statusEl = document.getElementById('pane-status');
    const renameBtn = document.getElementById('rename-agent');
    if (!a) {
      if (titleEl) titleEl.textContent = 'No agent selected';
      if (statusEl) statusEl.textContent = '';
      if (renameBtn) renameBtn.hidden = true;
      return;
    }
    if (titleEl) titleEl.textContent = a.title || 'Untitled';
    if (statusEl) statusEl.textContent = state.pendingByAgent[a.id] ? 'typing\u2026' : 'Agent';
    if (renameBtn) {
      renameBtn.hidden = false;
      renameBtn.onclick = async () => {
        const next = window.prompt('Rename agent', a.title || '');
        if (next == null) return;
        const t = next.trim();
        if (!t || t === a.title) return;
        try {
          const updated = await api.renameAgent(a.id, t);
          store.upsertAgent(updated || { id: a.id, title: t });
        } catch (e) { alert('Rename failed: ' + e.message); }
      };
    }
  }

  function renderMessages(state) {
    const id = state.activeAgentId;
    if (!id) {
      messagesEl.innerHTML = '<div class="nm-empty-hero"><h2>Welcome to NeuralMesh</h2><p>Select an agent on the left or create a new one to start chatting on the decentralized AI network.</p></div>';
      return;
    }
    const msgs = state.messagesByAgent[id] || [];
    const a = state.agents.find(x => x.id === id);
    const pending = !!state.pendingByAgent[id];
    if (msgs.length === 0 && !pending) {
      messagesEl.innerHTML = '<div class="nm-empty-hero"><h2>' + escapeHtml(a && a.title || 'New conversation') + '</h2><p>Send your first message to start the conversation.</p></div>';
      return;
    }
    const html = msgs.map(function(m) {
      const role = m.role === 'user' ? 'user' : 'assistant';
      const avatar = role === 'user' ? 'U' : (initials(a && a.title) || 'A');
      return ''+
        '<div class="msg ' + role + '">' +
          '<div class="msg__avatar">' + escapeHtml(avatar) + '</div>' +
          '<div class="msg__body">' + escapeHtml(m.content || '') + '</div>' +
        '</div>';
    }).join('');
    const typing = pending ? '<div class="msg assistant"><div class="msg__avatar">' + escapeHtml(initials(a && a.title) || 'A') + '</div><div class="msg__body"><span class="msg__role">Assistant</span>typing\u2026</div></div>' : '';
    messagesEl.innerHTML = html + typing;
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  store.subscribe(function(state) {
    renderHeader(state);
    if (state.activeAgentId && state.activeAgentId !== lastAgentId) {
      lastAgentId = state.activeAgentId;
      if (!state.messagesByAgent[state.activeAgentId]) loadMessages(state.activeAgentId);
    }
    renderMessages(state);
  });
}
