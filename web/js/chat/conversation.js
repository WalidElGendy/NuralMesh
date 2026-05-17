// NeuralMesh chat — conversation pane: header + messages (v0.1)
import { store } from './store.js';
import { api } from './api.js';

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, function(c) {
    return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c];
  });
}

export function mountConversation(headerEl, messagesEl) {
  let lastAgentId = null;
  async function loadMessages(agentId) {
    if (!agentId) return;
    try {
      const list = await api.getMessages(agentId);
      store.setMessages(agentId, list);
    } catch (e) { console.error('getMessages failed', e); }
  }
  function renderHeader(state) {
    const a = state.agents.find(function(x){return x.id === state.activeAgentId;});
    if (!a) { headerEl.innerHTML = ''; return; }
    headerEl.innerHTML =
      '<div><div class="pane-title">' + escapeHtml(a.title || 'Untitled') + '</div>' +
      '<div class="pane-sub">Agent</div></div>';
  }
  function renderMessages(state) {
    const id = state.activeAgentId;
    if (!id) {
      messagesEl.innerHTML = '<div class="no-agent"><div>Select or create an agent to start chatting.</div></div>';
      return;
    }
    const msgs = state.messagesByAgent[id] || [];
    const pending = !!state.pendingByAgent[id];
    const html = msgs.map(function(m) {
      const cls = m.role === 'user' ? 'bubble user' : 'bubble assistant';
      return '<div class="' + cls + '">' + escapeHtml(m.content || '') + '</div>';
    }).join('') + (pending ? '<div class="bubble assistant typing">typing…</div>' : '');
    messagesEl.innerHTML = html;
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
