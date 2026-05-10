-- Migration 022: Track platform-paid Groq fallback usage.
CREATE TABLE IF NOT EXISTS groq_usage (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL CHECK (prompt_tokens >= 0),
    completion_tokens INTEGER NOT NULL CHECK (completion_tokens >= 0)
);

CREATE INDEX IF NOT EXISTS idx_groq_usage_timestamp ON groq_usage(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_groq_usage_user_id ON groq_usage(user_id);

COMMENT ON TABLE groq_usage IS 'Platform-paid Groq fallback token usage for beta routing analysis.';

ALTER TABLE nodes
ADD COLUMN IF NOT EXISTS model_versions JSONB NOT NULL DEFAULT '[]'::jsonb;
