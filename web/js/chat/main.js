// NeuralMesh chat — boot file (v0.1)
import { store } from './store.js';
import { api } from './api.js';
import { mountSidebar } from './sidebar.js';
import { mountConversation } from './conversation.js';
import { mountComposer } from './composer.js';
import { mountNotifications } from './notifications.js';

async function boot() {
  const sidebarEl = document.getElementById('sidebar');
  const paneHeaderEl = document.getElementById('pane-header');
  const messagesEl = document.getElementById('messages');
  const composerEl = document.getElementById('composer');
  if (!sidebarEl || !messagesEl || !composerEl) {
    console.error('chat: required DOM nodes missing');
    return;
  }
  mountSidebar(sidebarEl);
  mountConversation(paneHeaderEl, messagesEl);
  mountComposer(composerEl);
  mountNotifications();

  try {
    const agents = await api.listAgents();
    const list = Array.isArray(agents) ? agents : (agents && Array.isArray(agents.agents) ? agents.agents : (agents && Array.isArray(agents.items) ? agents.items : []));        const normalized = list.map(function(a) {return Object.assign({ unread: 0 }, a);
    });
    store.setAgents(normalized);
    if (normalized.length > 0) {
      store.setActive(normalized[0].id);
    }
  } catch (e) {
    console.error('listAgents failed', e);
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
