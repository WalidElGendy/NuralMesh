/// NeuralMesh chat — conversation pane: header + messages (v0.2)
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
    const brandSvg = '<svg class="nm-brand__logo" viewBox="0 0 36 32" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><defs><linearGradient id="nmLogoGrad" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#c4b5fd"/><stop offset="100%" stop-color="#7c5cff"/></linearGradient></defs><path d="M5 28 L5 8 Q5 5 8 5 Q11 5 13 8 L23 24 Q23 27 26 27 Q29 27 29 24 L29 8" fill="none" stroke="url(#nmLogoGrad)" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/><circle cx="33" cy="26" r="3.2" fill="url(#nmLogoGrad)"/></svg>';
      const agentName = (a && a.title) || 'NeuralMesh';
      const html = msgs.map(function(m) {
        const role = m.role === 'user' ? 'user' : 'assistant';
        if (role === 'user') {
          return '<div class="msg user"><div class="msg__body">' + escapeHtml(m.content || '') + '</div></div>';
        }
        return '<div class="msg assistant">' +
          '<div class="nm-brand">' + brandSvg + '<span class="nm-brand__name">' + escapeHtml(agentName) + '</span></div>' +
          '<div class="msg__body">' + escapeHtml(m.content || '') + '</div>' +
          '</div>';
      }).join('');
    const typing = pending ? '<div class="msg assistant nm-typing"><div class="nm-brand">' + brandSvg + '<span class="nm-brand__name">' + escapeHtml(agentName) + '</span></div><div class="msg__body nm-typing__body"><div class="nm-typing__row"><svg class="nm-mesh" viewBox="0 0 120 40" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><g class="nm-mesh__edges" stroke="currentColor" stroke-width="1" stroke-linecap="round" fill="none"><line x1="14" y1="20" x2="42" y2="10" class="nm-edge nm-edge--1"/><line x1="14" y1="20" x2="42" y2="30" class="nm-edge nm-edge--2"/><line x1="42" y1="10" x2="78" y2="20" class="nm-edge nm-edge--3"/><line x1="42" y1="30" x2="78" y2="20" class="nm-edge nm-edge--4"/><line x1="78" y1="20" x2="106" y2="10" class="nm-edge nm-edge--5"/><line x1="78" y1="20" x2="106" y2="30" class="nm-edge nm-edge--6"/><line x1="42" y1="10" x2="42" y2="30" class="nm-edge nm-edge--7"/></g><g class="nm-mesh__nodes" fill="currentColor"><circle cx="14"  cy="20" r="3.2" class="nm-node nm-node--1"/><circle cx="42"  cy="10" r="3.2" class="nm-node nm-node--2"/><circle cx="42"  cy="30" r="3.2" class="nm-node nm-node--3"/><circle cx="78"  cy="20" r="3.6" class="nm-node nm-node--4"/><circle cx="106" cy="10" r="3.2" class="nm-node nm-node--5"/><circle cx="106" cy="30" r="3.2" class="nm-node nm-node--6"/></g></svg><span class="nm-typing__label">thinking<span class="nm-typing__dots"><i></i><i></i><i></i></span></span></div></div></div>' : '';
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
