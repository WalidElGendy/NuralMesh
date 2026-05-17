// NeuralMesh chat — composer (textarea + send) (v0.1)
import { store } from './store.js';
import { api } from './api.js';

export function mountComposer(root) {
  root.innerHTML =
    '<textarea id="composer-input" placeholder="Message your agent… (⏎ to send, Shift+⏎ for newline)" rows="1"></textarea>' +
    '<button id="composer-send">Send</button>';
  const input = root.querySelector('#composer-input');
  const send = root.querySelector('#composer-send');

  function autosize() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 200) + 'px';
  }
  input.addEventListener('input', autosize);

  async function submit() {
    const state = store.get();
    const agentId = state.activeAgentId;
    if (!agentId) return;
    const text = input.value.trim();
    if (!text) return;
    if (state.pendingByAgent[agentId]) return;
    input.value = '';
    autosize();
    const now = new Date().toISOString();
    store.appendMessage(agentId, { id: 'tmp-' + Date.now(), role: 'user', content: text, created_at: now });
    store.setPending(agentId, true);
    try {
      const r = await api.sendTurn(agentId, text);
      if (r && r.assistant_message) {
        store.appendMessage(agentId, r.assistant_message);
      }
      if (r && r.agent) {
        store.upsertAgent(r.agent);
      }
    } catch (e) {
      console.error('sendTurn failed', e);
      store.appendMessage(agentId, { id: 'err-' + Date.now(), role: 'assistant', content: '[error] ' + e.message, created_at: new Date().toISOString() });
    } finally {
      store.setPending(agentId, false);
    }
  }

  send.addEventListener('click', submit);
  input.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
  });

  store.subscribe(function(state) {
    const agentId = state.activeAgentId;
    const pending = agentId ? !!state.pendingByAgent[agentId] : false;
    send.disabled = !agentId || pending;
    input.disabled = !agentId;
  });
}
