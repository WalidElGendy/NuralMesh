-- Provider onboarding, claim-token, node credential, and beta payout schema.

create table if not exists provider_claim_tokens (
    claim_token text primary key,
    email text not null,
    gpu_model text,
    region text,
    provider_id text,
    expires_at timestamptz not null,
    used_at timestamptz,
    created_at timestamptz not null default now()
);

create table if not exists providers (
    id text primary key,
    email text not null,
    node_id text not null unique,
    node_secret_hash text not null,
    hostname text,
    gpu_info jsonb not null default '{}'::jsonb,
    status text not null default 'offline',
    last_seen_at timestamptz,
    tokens_today integer not null default 0,
    tokens_week integer not null default 0,
    tokens_month integer not null default 0,
    latency_p50_ms integer,
    latency_p95_ms integer,
    success_rate numeric(6, 5),
    models jsonb not null default '["llama3.3:70b-instruct-q4_K_M"]'::jsonb,
    payout_method jsonb not null default '{}'::jsonb,
    tax_info_status text not null default 'required_before_first_payout',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists provider_jobs (
    id text primary key,
    provider_id text not null references providers(id),
    node_id text not null references providers(node_id),
    prompt_preview text,
    tokens_served integer not null default 0,
    credits numeric(14, 4) not null default 0,
    status text not null default 'success',
    latency_ms integer,
    created_at timestamptz not null default now()
);

create table if not exists provider_payouts (
    id text primary key,
    provider_id text not null references providers(id),
    period text not null,
    credits numeric(14, 4) not null,
    usd_equivalent numeric(14, 2) not null,
    payout_method jsonb not null default '{}'::jsonb,
    status text not null default 'pending',
    created_at timestamptz not null default now(),
    paid_at timestamptz
);

create index if not exists idx_provider_claim_tokens_email on provider_claim_tokens(email);
create index if not exists idx_provider_claim_tokens_expires_at on provider_claim_tokens(expires_at);
create index if not exists idx_providers_last_seen_at on providers(last_seen_at desc);
create index if not exists idx_provider_jobs_period on provider_jobs(created_at);
create index if not exists idx_provider_jobs_provider_id on provider_jobs(provider_id);
