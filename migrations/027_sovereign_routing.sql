-- Migration 027: the sovereign job queue and routing ledger
--
-- GOAL
-- Every token served by a MeshNet GPU provider is a token you do not buy from
-- an outside LLM. The target is 100% mesh; the practical path is fallback to
-- DeepSeek-V3.1 while provider capacity is thin, with the fallback share
-- falling automatically as nodes come online. That only works if routing is
-- capacity-aware and every fallback is *recorded with a reason*, because the
-- reason codes are the provider-recruitment roadmap.
--
-- WHY THIS IS A NEW BUILD, NOT A TWEAK
-- api.py already exposes /api/node/jobs/next, /complete and /error against a
-- table called `jobs`. That table does not exist in this database:
--
--     select to_regclass('public.jobs');   -->  null
--
-- So the mesh dispatch path has never executed. `providers` has rows and
-- `provider_jobs` has none, which is consistent: no job has ever been served
-- by a node. The queue below is the first working version.
--
-- DESIGN NOTES
-- * PULL, not push. GPU providers are home users behind NAT with no inbound
--   ports. Nodes long-poll for work; the API relays their output chunks to the
--   browser over SSE. Requiring inbound connectivity would exclude exactly the
--   consumer GPUs the network is built on.
-- * LEASES. The old design set status='processing' with no expiry, so a node
--   that crashed mid-job stranded that job forever. Every claim now carries
--   lease_expires_at and is reclaimed automatically.
-- * FAIL FAST. A job unclaimed past its dispatch deadline is abandoned and the
--   turn falls back, before the user has seen a single token.

-- ---------------------------------------------------------------------------
-- 1. provider capacity and health
-- ---------------------------------------------------------------------------

alter table providers
  add column if not exists max_concurrent       integer not null default 1,
  add column if not exists consecutive_failures integer not null default 0,
  add column if not exists cooldown_until       timestamptz,
  add column if not exists accepts              boolean not null default true,
  add column if not exists first_served_at      timestamptz,
  add column if not exists total_tokens_served  bigint  not null default 0;

comment on column providers.max_concurrent is
  'How many jobs this node may hold at once. One 24GB card running a 70B q4
   model realistically serves one stream; larger nodes raise it.';
comment on column providers.cooldown_until is
  'Circuit breaker. Set when consecutive_failures crosses the threshold so a
   sick node stops receiving traffic without being deregistered.';
comment on column providers.accepts is
  'Provider-controlled pause switch. Distinct from status, which is observed.';

-- ---------------------------------------------------------------------------
-- 2. the job queue
-- ---------------------------------------------------------------------------

create table if not exists jobs (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid,
  conversation_id   uuid,
  model             text        not null,
  messages          jsonb       not null,
  params            jsonb       not null default '{}'::jsonb,

  status            text        not null default 'pending'
                    check (status in ('pending','claimed','streaming','complete','error','expired','abandoned')),
  node_id           text,
  served_by         text,

  created_at        timestamptz not null default now(),
  dispatch_deadline timestamptz not null default (now() + interval '4 seconds'),
  claimed_at        timestamptz,
  lease_expires_at  timestamptz,
  first_chunk_at    timestamptz,
  completed_at      timestamptz,

  prompt_tokens     integer not null default 0,
  completion_tokens integer not null default 0,
  total_tokens      integer not null default 0,
  tokens_served     integer not null default 0,
  latency_ms        integer,
  ttft_ms           integer,

  output            text,
  error             text,
  attempts          integer not null default 0
);

comment on table jobs is
  'Inference work offered to mesh nodes. A job that is not claimed before
   dispatch_deadline is abandoned and the caller falls back — the user never
   waits on an empty mesh.';

create index if not exists jobs_dispatch_idx
  on jobs (model, created_at)
  where status = 'pending';
create index if not exists jobs_lease_idx
  on jobs (lease_expires_at)
  where status in ('claimed','streaming');
create index if not exists jobs_node_idx      on jobs (node_id, created_at desc);
create index if not exists jobs_created_idx   on jobs (created_at desc);

-- Streamed output arrives in pieces; the API relays them to the browser.
create table if not exists job_chunks (
  job_id     uuid    not null references jobs(id) on delete cascade,
  seq        integer not null,
  content    text    not null,
  created_at timestamptz not null default now(),
  primary key (job_id, seq)
);

comment on table job_chunks is
  'Incremental tokens posted by a node. Deleted with the job; retained only
   long enough to relay to the connected client.';

-- ---------------------------------------------------------------------------
-- 3. the routing ledger — every turn, mesh or not, and WHY
-- ---------------------------------------------------------------------------

create table if not exists routing_events (
  id            bigserial primary key,
  created_at    timestamptz not null default now(),
  user_id       uuid,
  job_id        uuid,
  target        text not null check (target in ('mesh','fallback')),
  node_id       text,
  model         text,
  -- Why this did not go to the mesh. NULL when target = 'mesh'.
  -- These codes are the recruitment roadmap: 'no_nodes' means go find
  -- providers, 'no_capacity' means the ones you have are saturated,
  -- 'unclaimed' means they are online but too slow to pick work up.
  reason        text check (reason in (
                  'no_nodes','no_capacity','unhealthy','model_unavailable',
                  'unclaimed','node_error','share_cap','disabled')),
  tokens        integer not null default 0,
  latency_ms    integer,
  ttft_ms       integer,
  -- What this turn cost the platform in cash (fallback) and what it earned a
  -- provider in credits (mesh). One of the two is always zero.
  cost_usd      numeric(12,6) not null default 0,
  credits       numeric(12,6) not null default 0
);

create index if not exists routing_events_time_idx   on routing_events (created_at desc);
create index if not exists routing_events_target_idx on routing_events (target, created_at desc);
create index if not exists routing_events_reason_idx on routing_events (reason, created_at desc)
  where reason is not null;

-- ---------------------------------------------------------------------------
-- 4. atomic claim
--
-- SKIP LOCKED so concurrent pollers never hand the same job to two nodes, and
-- never block each other. Model-aware, and ordered oldest-first so no request
-- starves.
-- ---------------------------------------------------------------------------

create or replace function claim_next_job(
  p_node_id  text,
  p_models   text[] default null,
  p_lease_s  integer default 120
)
returns setof jobs
language plpgsql
security definer
set search_path = public
as $$
declare
  v_max     integer;
  v_current integer;
begin
  select coalesce(max_concurrent, 1) into v_max
    from providers
   where node_id = p_node_id
     and accepts
     and (cooldown_until is null or cooldown_until < now());
  if v_max is null then
    return;                                   -- unknown, paused, or cooling down
  end if;

  select count(*) into v_current
    from jobs
   where node_id = p_node_id
     and status in ('claimed','streaming')
     and lease_expires_at > now();
  if v_current >= v_max then
    return;                                   -- node is already at capacity
  end if;

  return query
  with candidate as (
    select j.id
      from jobs j
     where j.status = 'pending'
       and j.dispatch_deadline > now()
       and (p_models is null or j.model = any(p_models))
     order by j.created_at
     for update skip locked
     limit 1
  )
  update jobs j
     set status           = 'claimed',
         node_id          = p_node_id,
         served_by        = p_node_id,
         claimed_at       = now(),
         lease_expires_at = now() + make_interval(secs => p_lease_s),
         attempts         = j.attempts + 1
    from candidate c
   where j.id = c.id
  returning j.*;
end;
$$;

comment on function claim_next_job is
  'Hand one pending job to a node, respecting its concurrency limit, cooldown
   and advertised models. SKIP LOCKED makes concurrent polling safe.';

-- ---------------------------------------------------------------------------
-- 5. reaping
--
-- A node that dies mid-stream must not strand the job. Expired leases return
-- the job to the queue if the dispatch window is still open, otherwise mark it
-- abandoned so the caller's fallback is recorded honestly.
-- ---------------------------------------------------------------------------

create or replace function expire_stale_jobs()
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  n integer;
begin
  with expired as (
    update jobs
       set status  = case when dispatch_deadline > now() then 'pending' else 'expired' end,
           node_id = null,
           lease_expires_at = null,
           error   = coalesce(error, 'lease_expired')
     where status in ('claimed','streaming')
       and lease_expires_at < now()
    returning served_by
  )
  select count(*) into n from expired;

  -- A node whose lease lapsed gets a failure mark; enough of them trip the
  -- breaker and it stops receiving work until it recovers.
  update providers p
     set consecutive_failures = p.consecutive_failures + 1,
         cooldown_until = case
           when p.consecutive_failures + 1 >= 3 then now() + interval '10 minutes'
           else p.cooldown_until end
   where p.node_id in (
     select served_by from jobs
      where status in ('expired','abandoned')
        and served_by is not null
        and completed_at is null
        and created_at > now() - interval '15 minutes'
   );

  update jobs
     set status = 'abandoned'
   where status = 'pending'
     and dispatch_deadline < now() - interval '30 seconds';

  delete from job_chunks c
   using jobs j
   where c.job_id = j.id
     and j.completed_at < now() - interval '1 hour';

  return coalesce(n, 0);
end;
$$;

do $$
begin
  if exists (select 1 from pg_extension where extname = 'pg_cron') then
    perform cron.unschedule('mesh-reap-jobs')
      where exists (select 1 from cron.job where jobname = 'mesh-reap-jobs');
    perform cron.schedule('mesh-reap-jobs', '* * * * *', 'select expire_stale_jobs()');
  end if;
end;
$$;

-- ---------------------------------------------------------------------------
-- 6. sovereignty metrics
--
-- The single number the business is steered by: what share of tokens the mesh
-- served, and what the remainder cost in cash.
-- ---------------------------------------------------------------------------

create or replace view sovereignty_daily as
select
  date_trunc('day', created_at)::date                                     as day,
  count(*)                                                                as turns,
  count(*) filter (where target = 'mesh')                                 as mesh_turns,
  sum(tokens)                                                             as tokens,
  sum(tokens) filter (where target = 'mesh')                              as mesh_tokens,
  round(
    coalesce(sum(tokens) filter (where target = 'mesh'), 0)::numeric
    / nullif(sum(tokens), 0), 4)                                          as mesh_share,
  round(sum(cost_usd), 4)                                                 as fallback_cost_usd,
  round(sum(credits), 4)                                                  as provider_credits,
  mode() within group (order by reason) filter (where reason is not null)  as top_fallback_reason
from routing_events
group by 1
order by 1 desc;

comment on view sovereignty_daily is
  'Daily mesh share, the cash the fallback cost, what providers earned, and
   the most common reason the mesh was skipped. mesh_share -> 1.0 is the goal.';

create or replace view fallback_reasons_7d as
select reason,
       count(*)   as turns,
       sum(tokens) as tokens,
       round(sum(cost_usd), 4) as cost_usd
  from routing_events
 where target = 'fallback'
   and created_at > now() - interval '7 days'
 group by reason
 order by tokens desc;

comment on view fallback_reasons_7d is
  'Why the mesh was skipped this week, most expensive first. This is the
   provider-recruitment backlog in priority order.';

-- ---------------------------------------------------------------------------
-- 7. row level security
-- ---------------------------------------------------------------------------

alter table jobs           enable row level security;
alter table job_chunks     enable row level security;
alter table routing_events enable row level security;

drop policy if exists jobs_owner on jobs;
create policy jobs_owner on jobs
  for select to authenticated
  using (user_id = auth.uid());

drop policy if exists routing_events_owner on routing_events;
create policy routing_events_owner on routing_events
  for select to authenticated
  using (user_id = auth.uid());

-- Nodes and the dispatcher reach these through the service role, which
-- bypasses RLS; no policy is granted to anon.
grant select on sovereignty_daily, fallback_reasons_7d to authenticated;
