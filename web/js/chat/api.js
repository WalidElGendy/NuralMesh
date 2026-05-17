// NeuralMesh chat — API wrapper (v0.1)
// Reads bearer token from localStorage key 'nm_access_token'.

const BASE = '/api';
function tok() { try { return localStorage.getItem('nm_access_token') || ''; } catch { return ''; } }
async function req(path, opts = {}) {
  const headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
  const t = tok();
  if (t) headers['Authorization'] = 'Bearer ' + t;
  const r = await fetch(BASE + path, Object.assign({}, opts, { headers }));
  if (r.status === 401) {
    try { localStorage.removeItem('nm_access_token'); } catch {}
    window.location.href = '/login.html?next=' + encodeURIComponent(window.location.pathname);
    throw new Error('unauthorized');
  }
  const ct = r.headers.get('content-type') || '';
  const body = ct.includes('application/json') ? await r.json() : await r.text();
  if (!r.ok) {
    const msg = (body && body.detail) || (typeof body === 'string' ? body : 'request_failed');
    throw new Error(msg);
  }
  return body;
}
export const api = {
  listAgents: () => req('/agents'),
  createAgent: (title) => req('/agents', { method: 'POST', body: JSON.stringify({ title: title || 'New chat' }) }),
  renameAgent: (id, title) => req('/agents/' + id, { method: 'PATCH', body: JSON.stringify({ title }) }),
  deleteAgent: (id) => req('/agents/' + id, { method: 'DELETE' }),
  getMessages: (id) => req('/agents/' + id + '/messages'),
  sendTurn: (id, content) => req('/agents/' + id + '/turn', { method: 'POST', body: JSON.stringify({ content }) }),
};
