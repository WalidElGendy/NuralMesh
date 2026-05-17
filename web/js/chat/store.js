// NeuralMesh chat — tiny pub/sub store (v0.1)
// State shape:
//   agents: Array<{id, title, last_message_at, last_preview, unread}>
//   activeAgentId: string|null
//   messagesByAgent: { [agentId]: Array<{id, role, content, created_at}> }
//   pendingByAgent: { [agentId]: boolean }   // true while assistant is replying

export const store = (() => {
  const state = {
    agents: [],
    activeAgentId: null,
    messagesByAgent: {},
    pendingByAgent: {},
  };
  const subs = new Set();
  function emit() { for (const fn of subs) { try { fn(state); } catch (e) { console.error(e); } } }
  return {
    get: () => state,
    subscribe(fn) { subs.add(fn); fn(state); return () => subs.delete(fn); },
    setAgents(list) { state.agents = list.slice(); emit(); },
    upsertAgent(a) {
      const i = state.agents.findIndex(x => x.id === a.id);
      if (i >= 0) state.agents[i] = { ...state.agents[i], ...a };
      else state.agents.unshift(a);
      emit();
    },
    removeAgent(id) {
      state.agents = state.agents.filter(x => x.id !== id);
      delete state.messagesByAgent[id];
      delete state.pendingByAgent[id];
      if (state.activeAgentId === id) state.activeAgentId = null;
      emit();
    },
    setActive(id) {
      state.activeAgentId = id;
      const a = state.agents.find(x => x.id === id);
      if (a && a.unread) { a.unread = 0; }
      emit();
    },
    setMessages(agentId, messages) {
      state.messagesByAgent[agentId] = messages.slice();
      emit();
    },
    appendMessage(agentId, msg) {
      if (!state.messagesByAgent[agentId]) state.messagesByAgent[agentId] = [];
      state.messagesByAgent[agentId].push(msg);
      const a = state.agents.find(x => x.id === agentId);
      if (a) {
        a.last_message_at = msg.created_at || new Date().toISOString();
        a.last_preview = (msg.content || '').slice(0, 80);
        if (state.activeAgentId !== agentId && msg.role === 'assistant') {
          a.unread = (a.unread || 0) + 1;
        }
      }
      emit();
    },
    setPending(agentId, v) { state.pendingByAgent[agentId] = !!v; emit(); },
  };
})();
