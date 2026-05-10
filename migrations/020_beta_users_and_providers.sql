-- Beta production users, providers, and provider earnings.
create extension if not exists pgcrypto;

create table if not exists users (
    id uuid primary key default gen_random_uuid(),
    email text unique not null,
    password_hash text,
    display_name text,
    stripe_customer_id text,
    subscription_status text not null default 'none',
    invite_code_used text,
    created_at timestamptz not null default now()
);

create table if not exists providers (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references users(id) on delete cascade unique,
    gpu_description text,
    node_id text unique,
    accepted_terms_at timestamptz,
    payout_method text,
    created_at timestamptz not null default now()
);

create table if not exists provider_earnings (
    id uuid primary key default gen_random_uuid(),
    provider_id uuid not null references providers(id) on delete cascade,
    period_start date not null,
    period_end date not null,
    jobs_served int not null default 0,
    tokens_served bigint not null default 0,
    credits_earned numeric not null default 0,
    paid_out boolean not null default false,
    paid_out_at timestamptz,
    csv_export_id text
);

create index if not exists idx_users_email on users(email);
create index if not exists idx_providers_node_id on providers(node_id);
create index if not exists idx_provider_earnings_period on provider_earnings(period_start, period_end);
create index if not exists idx_provider_earnings_provider_period on provider_earnings(provider_id, period_start, period_end);
