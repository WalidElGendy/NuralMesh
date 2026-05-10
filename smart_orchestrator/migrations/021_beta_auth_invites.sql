-- Production beta auth, subscription, provider, and invite tables.

create table if not exists users (
    id uuid primary key,
    email text not null unique,
    role text not null default 'user',
    subscription_status text not null default 'none',
    stripe_customer_id text unique,
    stripe_subscription_id text,
    subscription_current_period_end timestamptz,
    trial_started_at timestamptz not null default now(),
    trial_request_count integer not null default 0,
    invite_code_used text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists providers (
    user_id uuid primary key references users(id) on delete cascade,
    status text not null default 'pending_terms',
    accepted_terms_at timestamptz,
    accepted_terms_version text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists invites (
    code text primary key,
    status text not null default 'unclaimed',
    parent_code text references invites(code),
    created_by_user_id text,
    claimed_by_user_id uuid references users(id),
    claimed_at timestamptz,
    created_at timestamptz not null default now()
);

create index if not exists idx_invites_created_by_user_id on invites(created_by_user_id);
create index if not exists idx_users_stripe_customer_id on users(stripe_customer_id);

