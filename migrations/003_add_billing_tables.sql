-- Billing and plan metadata for NeuralMesh API access.
-- This demo schema keeps user_id as text so it can work before a full auth system exists.

create table if not exists plans (
    id text primary key,
    name text not null unique,
    price_monthly numeric(10, 2) not null,
    request_limit integer not null,
    compute_hours_limit numeric(10, 2) not null
);

create table if not exists billing (
    user_id text primary key,
    plan_id text not null references plans(id),
    api_key text not null unique,
    requests_today integer not null default 0,
    compute_hours_used numeric(10, 2) not null default 0,
    stripe_customer_id text,
    stripe_subscription_id text,
    reset_at timestamptz not null default (now() + interval '1 day')
);

insert into plans (id, name, price_monthly, request_limit, compute_hours_limit)
values
    ('free', 'Free', 0, 100, 5),
    ('pro', 'Pro', 49, 10000, 100),
    ('enterprise', 'Enterprise', 499, 1000000, 10000)
on conflict (id) do update set
    name = excluded.name,
    price_monthly = excluded.price_monthly,
    request_limit = excluded.request_limit,
    compute_hours_limit = excluded.compute_hours_limit;

insert into billing (
    user_id,
    plan_id,
    api_key,
    requests_today,
    compute_hours_used,
    reset_at
)
values (
    'demo-user',
    'pro',
    'nm_live_sk_3f9a8b2c1d4e5f6a7b8c9d0e1f2a3b4c',
    1284,
    18.4,
    now() + interval '1 day'
)
on conflict (user_id) do update set
    plan_id = excluded.plan_id,
    api_key = excluded.api_key,
    requests_today = excluded.requests_today,
    compute_hours_used = excluded.compute_hours_used;
