-- Migration 030: anyone can run a node; strangers only see public work
--
-- The installer now accepts any NVIDIA or AMD GPU or Apple Silicon Mac with
-- 6 GB+ (it sizes the model to the machine). A node run by someone we have
-- not vetted is an 'open' node: the text of a job is visible on that machine
-- while it runs, and no encryption changes that. So:
--
--   providers.trust  'open' (default for every new node) | 'trusted' (vetted)
--   jobs.privacy     'private' (default) | 'public'
--
-- claim_next_job never hands a private job to an open node. Company and
-- workspace data is private by default; only turns the user marks public
-- (community chats) reach open nodes. Nodes registered before this change
-- were onboarded by invite and stay trusted.

do $$ begin
  if not exists (select 1 from information_schema.columns where table_name = 'providers' and column_name = 'trust') then
    alter table providers add column trust text not null default 'open';
    update providers set trust = 'trusted';   -- every node so far came in by invite
  end if;
end $$;
alter table providers drop constraint if exists providers_trust_check;
alter table providers add constraint providers_trust_check check (trust in ('open', 'trusted'));

alter table jobs add column if not exists privacy text not null default 'private';
alter table jobs drop constraint if exists jobs_privacy_check;
alter table jobs add constraint jobs_privacy_check check (privacy in ('private', 'public'));

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
  v_trust   text;
begin
  select coalesce(max_concurrent, 1), trust into v_max, v_trust
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
       and (v_trust = 'trusted' or j.privacy = 'public')   -- open nodes: public work only
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
  'Hand one pending job to a node, respecting its concurrency limit, cooldown,
   advertised models and trust: an open node only ever receives public jobs.';
