const low = require('lowdb');
const FileSync = require('lowdb/adapters/FileSync');
const path = require('path');
const { v4: uuidv4 } = require('uuid');
const bcrypt = require('bcryptjs');

const dataDir = process.env.RAILWAY_VOLUME_MOUNT_PATH || '/tmp';
const dbPath = path.join(dataDir, 'meshnet-db.json');

const adapter = new FileSync(dbPath);
const db = low(adapter);

// Set defaults
db.defaults({
  users: [],
  api_keys: [],
  nodes: [],
  jobs: [],
  payouts: []
}).write();

// Seed iPad node SA-01 if not exists
const existingNode = db.get('nodes').find({ id: 'node-ipad-01' }).value();
if (!existingNode) {
  const providerId = 'provider-seed-01';
  const existingProvider = db.get('users').find({ id: providerId }).value();
  if (!existingProvider) {
    const hash = bcrypt.hashSync('MeshNet2026!', 10);
    db.get('users').push({
      id: providerId,
      email: 'node@meshnet.co',
      password_hash: hash,
      name: 'Node SA-01',
      role: 'provider',
      created_at: new Date().toISOString()
    }).write();
  }
  db.get('nodes').push({
    id: 'node-ipad-01',
    provider_id: providerId,
    name: 'Node SA-01',
    location: 'Saudi Arabia',
    gpu_model: 'iPad (Groq Proxy)',
    status: 'online',
    payout_currency: 'SAR',
    bank_details: '{}',
    jobs_completed: 0,
    uptime_pct: 99.9,
    last_heartbeat: new Date().toISOString(),
    created_at: new Date().toISOString()
  }).write();
}

// Sync-style DB wrapper to keep server.js API compatible
const dbWrapper = {
  prepare: (sql) => {
    // Parse SQL to determine operation
    return {
      get: (...params) => dbWrapper._get(sql, params),
      all: (...params) => dbWrapper._all(sql, params),
      run: (...params) => dbWrapper._run(sql, params)
    };
  },
  _get: (sql, params) => {
    const s = sql.toLowerCase().trim();
    if (s.includes('from users where email')) {
      return db.get('users').find({ email: params[0] }).value() || null;
    }
    if (s.includes('from users where id')) {
      const u = db.get('users').find({ id: params[0] }).value();
      if (!u) return null;
      if (s.includes('select id from users')) return { id: u.id };
      return u;
    }
    if (s.includes('from api_keys where key_value')) {
      return db.get('api_keys').find({ key_value: params[0], active: 1 }).value() || null;
    }
    if (s.includes('from nodes where id')) {
      return db.get('nodes').find({ id: params[0] }).value() || null;
    }
    if (s.includes('count(*) as count from nodes')) {
      const status = params[0];
      return { count: db.get('nodes').filter({ status }).value().length };
    }
    if (s.includes('count(*) as count from jobs')) {
      const cutoff = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
      return { count: db.get('jobs').filter(j => j.created_at >= cutoff).value().length };
    }
    if (s.includes('sum(tokens_used)')) {
      const cutoff = new Date(Date.now() - 7 * 24 * 3600 * 1000).toISOString();
      const total = db.get('jobs').filter(j => j.created_at >= cutoff).reduce((sum, j) => sum + (j.tokens_used || 0), 0).value();
      return { total };
    }
    return null;
  },
  _all: (sql, params) => {
    const s = sql.toLowerCase().trim();
    if (s.includes('from api_keys where user_id')) {
      return db.get('api_keys').filter({ user_id: params[0] }).value();
    }
    if (s.includes('from nodes where status !=')) {
      return db.get('nodes').filter(n => n.status !== params[0]).value();
    }
    if (s.includes('from nodes where status =')) {
      return db.get('nodes').filter({ status: params[0] }).value();
    }
    if (s.includes('from jobs where user_id')) {
      return db.get('jobs').filter({ user_id: params[0] }).sortBy('created_at').reverse().take(50).value();
    }
    if (s.includes('from jobs j left join')) {
      const jobs = db.get('jobs').sortBy('created_at').reverse().take(100).value();
      return jobs.map(j => {
        const user = db.get('users').find({ id: j.user_id }).value();
        return { ...j, email: user ? user.email : 'unknown' };
      });
    }
    return [];
  },
  _run: (sql, params) => {
    const s = sql.toLowerCase().trim();
    if (s.startsWith('insert into users')) {
      db.get('users').push({
        id: params[0], email: params[1], password_hash: params[2],
        name: params[3], role: params[4], created_at: params[5]
      }).write();
    } else if (s.startsWith('insert into api_keys')) {
      db.get('api_keys').push({
        id: params[0], user_id: params[1], label: params[2],
        key_value: params[3], active: 1, created_at: params[4]
      }).write();
    } else if (s.startsWith('update api_keys set active = 0')) {
      db.get('api_keys').find({ id: params[0], user_id: params[1] }).assign({ active: 0 }).write();
    } else if (s.startsWith('insert into nodes')) {
      db.get('nodes').push({
        id: params[0], provider_id: params[1], name: params[2], location: params[3],
        gpu_model: params[4], status: params[5], payout_currency: params[6],
        bank_details: params[7], jobs_completed: 0, uptime_pct: 0,
        created_at: params[8]
      }).write();
    } else if (s.startsWith('update nodes set status')) {
      db.get('nodes').find({ id: params[2] }).assign({ status: params[0], last_heartbeat: params[1] }).write();
    } else if (s.startsWith('insert into jobs') || s.startsWith('insert or ignore into jobs')) {
      db.get('jobs').push({
        id: params[0], user_id: params[1], node_id: params[2], model: params[3],
        tokens_used: params[4], latency_ms: params[5], status: params[6], created_at: params[7]
      }).write();
    }
    return { changes: 1 };
  }
};

module.exports = dbWrapper;
