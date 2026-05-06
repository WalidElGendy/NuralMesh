const Database = require('better-sqlite3');
const path = require('path');
const fs = require('fs');

const dataDir = process.env.RAILWAY_VOLUME_MOUNT_PATH || '/tmp';
const dbPath = path.join(dataDir, 'meshnet.db');

const db = new Database(dbPath);

db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

db.exec(`
  CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    label TEXT NOT NULL,
    key_value TEXT UNIQUE NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
  );

  CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    name TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT 'Unknown',
    gpu_model TEXT NOT NULL DEFAULT 'CPU',
    status TEXT NOT NULL DEFAULT 'offline',
    payout_currency TEXT NOT NULL DEFAULT 'USD',
    bank_details TEXT NOT NULL DEFAULT '{}',
    jobs_completed INTEGER NOT NULL DEFAULT 0,
    uptime_pct REAL NOT NULL DEFAULT 0,
    last_heartbeat TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (provider_id) REFERENCES users(id)
  );

  CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    node_id TEXT,
    model TEXT NOT NULL,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'completed',
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
  );

  CREATE TABLE IF NOT EXISTS payouts (
    id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    amount REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    reference TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    FOREIGN KEY (provider_id) REFERENCES users(id)
  );
`);

// Seed iPad node SA-01 if not exists
const existing = db.prepare('SELECT id FROM nodes WHERE id = ?').get('node-ipad-01');
if (!existing) {
  // Create a seed provider user if none exists
  let providerId = 'provider-seed-01';
  const providerExists = db.prepare('SELECT id FROM users WHERE id = ?').get(providerId);
  if (!providerExists) {
    const bcrypt = require('bcryptjs');
    const hash = bcrypt.hashSync('MeshNet2026!', 10);
    db.prepare('INSERT OR IGNORE INTO users (id, email, password_hash, name, role, created_at) VALUES (?, ?, ?, ?, ?, ?)').run(providerId, 'node@meshnet.co', hash, 'Node SA-01', 'provider', new Date().toISOString());
  }
  db.prepare('INSERT OR IGNORE INTO nodes (id, provider_id, name, location, gpu_model, status, payout_currency, bank_details, jobs_completed, uptime_pct, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)').run('node-ipad-01', providerId, 'Node SA-01', 'Saudi Arabia', 'iPad (Groq Proxy)', 'online', 'SAR', '{}', 0, 99.9, new Date().toISOString());
}

module.exports = db;
