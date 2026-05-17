// NeuralMesh chat — composer (pill input, attach/emoji/send icons) (v0.2)
import { store } from './store.js';
import { api } from './api.js';

const ICON_PLUS = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>';
const ICON_SMILE = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>';
const ICON_SEND  = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>';
const ICON_MIC   = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>';

function deriveTitle(text) {
  const t = (text || '').replace(/\s+/g, ' ').trim();
  if (!t) return '';
  if (t.length <= 40) return t;
  return t.slice(0, 40).replace(/[\s,.;:!?-]+$/, '') + '…';
}

export function mountComposer(root) {
  // Render INSIDE #composer (do not overwrite siblings like the hint)
  root.innerHTML =
    '<div class="nm-composer__inner">' +
      '<button class="nm-composer__icon" id="composer-attach" type="button" title="Attach" aria-label="Attach">' + ICON_PLUS + '</button>' +
      '<textarea id="composer-input" rows="1" placeholder="Message your agent…" aria-label="Message"></textarea>' +
      '<button class="nm-composer__icon" id="composer-emoji" type="button" title="Emoji" aria-label="Emoji">' + ICON_SMILE + '</button>' +
      '<button class="nm-composer__send" id="composer-send" type="button" title="Send (Enter)" aria-label="Send">' + ICON_SEND + '</button>' +
    '</div>' +
    '<div class="nm-composer__hint">Enter to send • Shift+Enter for newline</div>';

  const input = root.querySelector('#composer-input');
  const sendBtn = root.querySelector('#composer-send');
  const attachBtn = root.querySelector('#composer-attach');
  const emojiBtn = root.querySelector('#composer-emoji');

  function autosize() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 200) + 'px';
  }
  input.addEventListener('input', () => {
    autosize();
    const hasText = input.value.trim().length > 0;
    sendBtn.innerHTML = hasText ? ICON_SEND : ICON_MIC;
    sendBtn.dataset.mode = hasText ? 'send' : 'mic';
  });

  // Initial icon state: mic when empty
  sendBtn.innerHTML = ICON_MIC;
  sendBtn.dataset.mode = 'mic';

  attachBtn.addEventListener('click', () => {
    // Stub: trigger a hidden file input later; for now, focus the textarea.
    input.focus();
  });
  emojiBtn.addEventListener('click', () => {
    // Simple emoji insert stub
    const pos = input.selectionStart || input.value.length;
    input.value = input.value.slice(0, pos) + '🙂' + input.value.slice(pos);
    input.dispatchEvent(new Event('input'));
    input.focus();
  });

  async function submit() {
    const state = store.get();
    const agentId = state.activeAgentId;
    if (!agentId) return;
    const text = input.value.trim();
    if (!text) return;
    if (state.pendingByAgent[agentId]) return;

    input.value = '';
    autosize();
    sendBtn.innerHTML = ICON_MIC;
    sendBtn.dataset.mode = 'mic';

    const now = new Date().toISOString();
    store.appendMessage(agentId, { id: 'tmp-' + Date.now(), role: 'user', content: text, created_at: now });
    store.setPending(agentId, true);

    // Auto-rename agent from first user message if title is still default
    try {
      const agent = state.agents.find(x => x.id === agentId);
      const currentTitle = (agent && agent.title || '').trim();
      const isDefault = !currentTitle || currentTitle === 'New chat' || currentTitle === 'Untitled';
      const msgs = state.messagesByAgent[agentId] || [];
      const hasPriorUser = msgs.some(m => m.role === 'user');
      if (isDefault && !hasPriorUser) {
        const newTitle = deriveTitle(text);
        if (newTitle) {
          api.renameAgent(agentId, newTitle).then(updated => {
            store.upsertAgent(updated || { id: agentId, title: newTitle });
          }).catch(err => console.warn('auto-rename failed', err));
        }
      }
    } catch (e) { /* non-fatal */ }

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
      store.appendMessage(agentId, {
        id: 'err-' + Date.now(), role: 'assistant',
        content: '[error] ' + e.message,
        created_at: new Date().toISOString()
      });
    } finally {
      store.setPending(agentId, false);
    }
  }

  sendBtn.addEventListener('click', () => {
    if (sendBtn.dataset.mode === 'send') submit();
    else input.focus();
  });

  input.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  });

  store.subscribe(function(state) {
    const agentId = state.activeAgentId;
    const pending = agentId ? !!state.pendingByAgent[agentId] : false;
    sendBtn.disabled = !agentId || pending;
    input.disabled = !agentId;
    input.placeholder = agentId ? 'Message your agent…' : 'Select or create an agent to start';
  });
}
