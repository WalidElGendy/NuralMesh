
-- Migration 006: Add nodes table for GPU node heartbeat tracking
CREATE TABLE IF NOT EXISTS nodes (
    id           TEXT PRIMARY KEY,
    node_id      TEXT NOT NULL,
    name         TEXT NOT NULL,
    location     TEXT NOT NULL DEFAULT 'unknown',
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nodes_last_seen ON nodes(last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_nodes_node_id ON nodes(node_id);

COMMENT ON TABLE nodes IS 'Registered GPU inference nodes. Heartbeat updated every 30s by node.py.';
