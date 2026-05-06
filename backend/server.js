const express = require('express');
const cors = require('cors');
const jwt = require('jsonwebtoken');
const bcrypt = require('bcryptjs');
const { v4: uuidv4 } = require('uuid');
const Groq = require('groq-sdk');
const db = require('./db');

const app = express();
const PORT = process.env.PORT || 3000;
const JWT_SECRET = process.env.JWT_SECRET || 'meshnet-secret-2026';
const GROQ_API_KEY = process.env.GROQ_API_KEY || '';

app.use(cors({ origin: '*' }));
app.use(express.json());

const groq = new Groq({ apiKey: GROQ_API_KEY });

function authMiddleware(req, res, next) {
  const auth = req.headers.authorization;
  if (!auth || !auth.startsWith('Bearer ')) return res.status(401).json({ error: 'Unauthorized' });
  try {
    req.user = jwt.verify(auth.slice(7), JWT_SECRET);
    next();
  } catch (e) {
    return res.status(401).json({ error: 'Invalid token' });
  }
}

function apiKeyMiddleware(req, res, next) {
  const apiKey = req.headers['x-api-key'];
  if (!apiKey) return res.status(401).json({ error: 'API key required' });
  const row = db.prepare('SELECT * FROM api_keys WHERE key_value = ? AND active = 1').get(apiKey);
  if (!row) return res.status(401).json({ error: 'Invalid or inactive API key' });
  req.apiKey = row;
  next();
}

app.get('/', (req, res) => res.json({ status: 'ok', service: 'MeshNet Backend', version: '1.0.0' }));
app.get('/health', (req, res) => res.json({ status: 'healthy', timestamp: new Date().toISOString() }));

app.post('/auth/register', async (req, res) => {
  const { email, password, name, role } = req.body;
  if (!email || !password || !name) return res.status(400).json({ error: 'Missing fields' });
  const existing = db.prepare('SELECT id FROM users WHERE email = ?').get(email);
  if (existing) return res.status(409).json({ error: 'Email already registered' });
  const hash = await bcrypt.hash(password, 10);
  const id = uuidv4();
  const userRole = role === 'provider' ? 'provider' : 'user';
  db.prepare('INSERT INTO users (id, email, password_hash, name, role, created_at) VALUES (?, ?, ?, ?, ?, ?)').run(id, email, hash, name, userRole, new Date().toISOString());
  const token = jwt.sign({ id, email, role: userRole }, JWT_SECRET, { expiresIn: '30d' });
  res.json({ token, user: { id, email, name, role: userRole } });
});

app.post('/auth/login', async (req, res) => {
  const { email, password } = req.body;
  if (!email || !password) return res.status(400).json({ error: 'Missing fields' });
  const user = db.prepare('SELECT * FROM users WHERE email = ?').get(email);
  if (!user) return res.status(401).json({ error: 'Invalid credentials' });
  const valid = await bcrypt.compare(password, user.password_hash);
  if (!valid) return res.status(401).json({ error: 'Invalid credentials' });
  const token = jwt.sign({ id: user.id, email: user.email, role: user.role }, JWT_SECRET, { expiresIn: '30d' });
  res.json({ token, user: { id: user.id, email: user.email, name: user.name, role: user.role } });
});

app.get('/auth/me', authMiddleware, (req, res) => {
  const user = db.prepare('SELECT id, email, name, role, created_at FROM users WHERE id = ?').get(req.user.id);
  res.json(user);
});

app.post('/api-keys', authMiddleware, (req, res) => {
  const { label } = req.body;
  const id = uuidv4();
  const keyValue = 'mn_' + uuidv4().replace(/-/g, '');
  db.prepare('INSERT INTO api_keys (id, user_id, label, key_value, active, created_at) VALUES (?, ?, ?, ?, 1, ?)').run(id, req.user.id, label || 'Default Key', keyValue, new Date().toISOString());
  res.json({ id, label: label || 'Default Key', key_value: keyValue, active: true });
});

app.get('/api-keys', authMiddleware, (req, res) => {
  const keys = db.prepare('SELECT id, label, key_value, active, created_at FROM api_keys WHERE user_id = ?').all(req.user.id);
  res.json(keys);
});

app.delete('/api-keys/:id', authMiddleware, (req, res) => {
  db.prepare('UPDATE api_keys SET active = 0 WHERE id = ? AND user_id = ?').run(req.params.id, req.user.id);
  res.json({ success: true });
});

app.get('/nodes', (req, res) => {
  const nodes = db.prepare('SELECT id, name, location, gpu_model, status, jobs_completed, uptime_pct FROM nodes WHERE status != ?').all('offline');
  res.json(nodes);
});

app.post('/nodes/register', authMiddleware, (req, res) => {
  const { name, location, gpu_model, payout_currency, bank_details } = req.body;
  if (req.user.role !== 'provider') return res.status(403).json({ error: 'Provider role required' });
  const id = 'node-' + uuidv4().slice(0, 8);
  db.prepare('INSERT INTO nodes (id, provider_id, name, location, gpu_model, status, payout_currency, bank_details, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)').run(id, req.user.id, name || 'My Node', location || 'Unknown', gpu_model || 'RTX 4090', 'provisioning', payout_currency || 'USD', JSON.stringify(bank_details || {}), new Date().toISOString());
  res.json({ id, status: 'provisioning', message: 'Node registered successfully' });
});

app.patch('/nodes/:id/heartbeat', (req, res) => {
  const nid = req.params.id;
  db.prepare('UPDATE nodes SET status = ?, last_heartbeat = ? WHERE id = ?').run('online', new Date().toISOString(), nid);
  res.json({ status: 'ok' });
});

app.post('/v1/chat/completions', apiKeyMiddleware, async (req, res) => {
  const { messages, model, stream, max_tokens } = req.body;
  if (!messages) return res.status(400).json({ error: 'messages required' });
  const groqModel = mapModel(model);
  const jobId = 'job-' + uuidv4().slice(0, 8);
  const startTime = Date.now();
  try {
    const nodes = db.prepare('SELECT id FROM nodes WHERE status = ?').all('online');
    const nodeId = nodes.length > 0 ? nodes[0].id : 'node-ipad-01';
    if (stream) {
      res.setHeader('Content-Type', 'text/event-stream');
      res.setHeader('Cache-Control', 'no-cache');
      const streamResp = await groq.chat.completions.create({ messages, model: groqModel, stream: true, max_tokens: max_tokens || 1024 });
      let totalTokens = 0;
      for await (const chunk of streamResp) {
        const delta = chunk.choices[0]?.delta;
        if (delta) {
          res.write('data: ' + JSON.stringify(chunk) + '\n\n');
          if (chunk.usage) totalTokens = chunk.usage.total_tokens;
        }
      }
      res.write('data: [DONE]\n\n');
      res.end();
      recordJob(jobId, req.apiKey.user_id, nodeId, groqModel, totalTokens, Date.now() - startTime, 'completed');
    } else {
      const resp = await groq.chat.completions.create({ messages, model: groqModel, max_tokens: max_tokens || 1024 });
      const tokens = resp.usage?.total_tokens || 0;
      recordJob(jobId, req.apiKey.user_id, nodeId, groqModel, tokens, Date.now() - startTime, 'completed');
      res.json(resp);
    }
  } catch (e) {
    console.error('Inference error:', e.message);
    recordJob(jobId, req.apiKey.user_id, null, groqModel, 0, Date.now() - startTime, 'failed');
    res.status(500).json({ error: e.message });
  }
});

function mapModel(model) {
  const map = { 'llama3-8b': 'llama3-8b-8192', 'llama3-70b': 'llama3-70b-8192', 'mistral-7b': 'mistral-small-2409', 'phi-3': 'gemma2-9b-it' };
  return map[model] || model || 'llama3-8b-8192';
}

function recordJob(id, userId, nodeId, model, tokens, latency, status) {
  try {
    db.prepare('INSERT INTO jobs (id, user_id, node_id, model, tokens_used, latency_ms, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)').run(id, userId, nodeId, model, tokens, latency, status, new Date().toISOString());
  } catch (e) { console.error('recordJob error:', e.message); }
}

app.get('/jobs', authMiddleware, (req, res) => {
  const jobs = db.prepare('SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC LIMIT 50').all(req.user.id);
  res.json(jobs);
});

app.get('/admin/jobs', authMiddleware, (req, res) => {
  const jobs = db.prepare('SELECT j.*, u.email FROM jobs j LEFT JOIN users u ON j.user_id = u.id ORDER BY j.created_at DESC LIMIT 100').all();
  res.json(jobs);
});

app.get('/stats', (req, res) => {
  const nodes = db.prepare('SELECT COUNT(*) as count FROM nodes WHERE status = ?').get('online');
  const jobs = db.prepare('SELECT COUNT(*) as count FROM jobs WHERE created_at >= datetime("now", "-1 day")').get();
  const tokens = db.prepare('SELECT SUM(tokens_used) as total FROM jobs WHERE created_at >= datetime("now", "-7 days")').get();
  res.json({ active_nodes: nodes.count, jobs_24h: jobs.count, tokens_7d: tokens.total || 0 });
});

app.listen(PORT, () => console.log('MeshNet backend running on port ' + PORT));
module.exports = app;
