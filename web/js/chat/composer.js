// NeuralMesh chat — composer (right-side attach + mic/send) (v0.3)
import { store } from './store.js';
import { api } from './api.js';

const ICON_PLUS = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>';
const ICON_SEND  = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>';
const ICON_MIC   = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>';

function deriveTitle(text) {
  const t = (text || '').replace(/\s+/g, ' ').trim();
  if (!t) return '';
  if (t.length <= 40) return t;
  return t.slice(0, 40).replace(/[\s,.;:!?-]+$/, '') + '…';
}

function fmtSize(bytes){
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024*1024) return (bytes/1024).toFixed(1) + ' KB';
  return (bytes/1024/1024).toFixed(1) + ' MB';
}

export function mountComposer(root) {
  // Render INSIDE #composer (keeps the hint outside if present in chat.html)
  root.innerHTML =
    '<div class="nm-composer__inner">' +
      '<textarea id="composer-input" rows="1" placeholder="Message your agent…" aria-label="Message"></textarea>' +
      '<input type="file" id="composer-file" hidden multiple accept="image/*,application/pdf,.doc,.docx,.txt,.csv,.xlsx,.pptx,audio/*,video/*">' +
      '<button class="nm-composer__icon" id="composer-attach" type="button" title="Attach file" aria-label="Attach file">' + ICON_PLUS + '</button>' +
      '<button class="nm-composer__send" id="composer-send" type="button" title="Send (Enter)" aria-label="Send">' + ICON_MIC + '</button>' +
    '</div>' +
    '<div class="nm-composer__attachments" id="composer-attachments"></div>' +
    '<div class="nm-composer__hint">Enter to send • Shift+Enter for newline</div>';

  const input = root.querySelector('#composer-input');
  const sendBtn = root.querySelector('#composer-send');
  const attachBtn = root.querySelector('#composer-attach');
  const fileEl = root.querySelector('#composer-file');
  const attachWrap = root.querySelector('#composer-attachments');

  let attachments = []; // {name, size, type, file}

  function renderAttachments(){
    if (!attachments.length){ attachWrap.innerHTML = ''; return; }
    attachWrap.innerHTML = attachments.map((a,i) =>
      '<span class="nm-chip" data-i="'+i+'">📎 '+escapeHtml(a.name)+' · '+fmtSize(a.size)+' <button class="nm-chip__x" data-i="'+i+'" aria-label="Remove">×</button></span>'
    ).join('');
    attachWrap.querySelectorAll('.nm-chip__x').forEach(btn => {
      btn.addEventListener('click', e => {
        const i = +btn.dataset.i;
        attachments.splice(i,1);
        renderAttachments();
        updateSendIcon();
      });
    });
  }
  function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}

  function updateSendIcon(){
    const hasText = input.value.trim().length > 0 || attachments.length > 0;
    sendBtn.innerHTML = hasText ? ICON_SEND : ICON_MIC;
    sendBtn.dataset.mode = hasText ? 'send' : 'mic';
  }

  function autosize() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 200) + 'px';
  }
  input.addEventListener('input', () => { autosize(); updateSendIcon(); });

  attachBtn.addEventListener('click', () => fileEl.click());
  fileEl.addEventListener('change', () => {
    for (const f of fileEl.files) {
      attachments.push({ name: f.name, size: f.size, type: f.type, file: f });
    }
    fileEl.value = '';
    renderAttachments();
    updateSendIcon();
  });

  async function uploadFile(f){
    // Try /api/upload, fall back to inlining filename only
    const fd = new FormData();
    fd.append('file', f);
    try {
      const tok = (function(){try{return localStorage.getItem('nm_access_token')||''}catch(e){return ''}})();
      const r = await fetch('/api/upload', {
        method:'POST',
        headers: tok ? { 'Authorization':'Bearer '+tok } : {},
        body: fd,
      });
      if (!r.ok) throw new Error('upload_failed_'+r.status);
      const j = await r.json().catch(()=>({}));
      return j.url || j.path || f.name;
    } catch(e){
      return null; // upload endpoint not available
    }
  }

  async function submit() {
    const state = store.get();
    const agentId = state.activeAgentId;
    if (!agentId) return;
    let text = input.value.trim();
    if (!text && !attachments.length) return;
    if (state.pendingByAgent[agentId]) return;

    // Upload attachments first; prefix their info to message content.
    let attachmentNote = '';
    if (attachments.length) {
      const lines = [];
      for (const a of attachments) {
        const url = await uploadFile(a.file);
        lines.push(url ? '['+a.name+']('+url+')' : '[file: '+a.name+' · '+fmtSize(a.size)+']');
      }
      attachmentNote = lines.join('\n');
    }
    const finalContent = [attachmentNote, text].filter(Boolean).join('\n\n') || (attachmentNote || text);

    input.value = '';
    attachments = [];
    renderAttachments();
    autosize();
    updateSendIcon();

    const now = new Date().toISOString();
    store.appendMessage(agentId, { id: 'tmp-' + Date.now(), role: 'user', content: finalContent, created_at: now });
    store.setPending(agentId, true);

    // Auto-rename agent from first user message if title is still default
    try {
      const agent = state.agents.find(x => x.id === agentId);
      const currentTitle = ((agent && agent.title) || '').trim();
      const isDefault = !currentTitle || currentTitle === 'New chat' || currentTitle === 'Untitled';
      const msgs = state.messagesByAgent[agentId] || [];
      const hasPriorUser = msgs.some(m => m.role === 'user');
      if (isDefault && !hasPriorUser && text) {
        const newTitle = deriveTitle(text);
        if (newTitle) {
          api.renameAgent(agentId, newTitle).then(updated => {
            store.upsertAgent(updated || { id: agentId, title: newTitle });
          }).catch(err => console.warn('auto-rename failed', err));
        }
      }
    } catch (e) { /* non-fatal */ }

    try {
      const r = await api.sendTurn(agentId, finalContent);
      if (r && r.assistant_message) store.appendMessage(agentId, r.assistant_message);
      if (r && r.agent) store.upsertAgent(r.agent);
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
    attachBtn.disabled = !agentId;
    input.placeholder = agentId ? 'Message your agent…' : 'Select or create an agent to start';
  });

  updateSendIcon();
}
