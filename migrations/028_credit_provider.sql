-- 028_credit_provider.sql
-- Settlement RPC: atomically credit a provider node for tokens served on a
-- completed mesh job. Called from mesh_router.record() (which fires from the
-- node-completion endpoint /api/node/jobs/{id}/complete).
--
-- total_tokens_served is the authoritative lifetime counter used by the
-- provider wallet and payouts. tokens_today/week/month are self-resetting
-- rolling windows keyed off last_seen_at, so no separate reset job is required:
-- the first credit after a day/week/month boundary starts the window fresh.

create or replace function public.credit_provider(
  p_node_id text,
  p_tokens bigint,
  p_credits numeric default 0
) returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  update public.providers p set
    total_tokens_served = coalesce(p.total_tokens_served, 0) + greatest(p_tokens, 0),
    tokens_today = case
      when p.last_seen_at is null or p.last_seen_at < date_trunc('day', now())
        then greatest(p_tokens, 0)
      else coalesce(p.tokens_today, 0) + greatest(p_tokens, 0)
    end,
    tokens_week = case
      when p.last_seen_at is null or p.last_seen_at < date_trunc('week', now())
        then greatest(p_tokens, 0)
      else coalesce(p.tokens_week, 0) + greatest(p_tokens, 0)
    end,
    tokens_month = case
      when p.last_seen_at is null or p.last_seen_at < date_trunc('month', now())
        then greatest(p_tokens, 0)
      else coalesce(p.tokens_month, 0) + greatest(p_tokens, 0)
    end,
    first_served_at = coalesce(p.first_served_at, now()),
    last_seen_at = now(),
    updated_at = now()
  where p.node_id = p_node_id;
end;
$$;

grant execute on function public.credit_provider(text, bigint, numeric)
  to service_role, authenticated, anon;
