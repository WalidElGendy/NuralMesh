-- Migration 029: magic-link and password-reset emails.
--
-- The nm-auth-link edge function sends these itself (through Resend), so it
-- needs two things from the database: whether an address belongs to an
-- account, and a throttle so the public "email me a link" / "forgot
-- password" buttons cannot be used to flood someone's inbox.
-- Only the service role (the edge function) can call it.

create table if not exists public.nm_auth_email_log (
  id bigserial primary key,
  email text not null,
  kind text not null check (kind in ('magiclink', 'recovery')),
  sent_at timestamptz not null default now()
);
create index if not exists nm_auth_email_log_email_idx on public.nm_auth_email_log (lower(email), sent_at desc);
alter table public.nm_auth_email_log enable row level security;   -- no policies: service role only

-- True (and logged) when the address has an account and has not had a link
-- in the last 60 seconds or more than 5 in the last hour.
create or replace function public.nm_auth_email_allowed(p_email text, p_kind text)
returns boolean
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  v_email text := lower(trim(p_email));
begin
  if p_kind not in ('magiclink', 'recovery') then return false; end if;
  if not exists (select 1 from auth.users where lower(email) = v_email) then return false; end if;
  if exists (select 1 from nm_auth_email_log where lower(email) = v_email and sent_at > now() - interval '60 seconds') then return false; end if;
  if (select count(*) from nm_auth_email_log where lower(email) = v_email and sent_at > now() - interval '1 hour') >= 5 then return false; end if;
  insert into nm_auth_email_log (email, kind) values (v_email, p_kind);
  return true;
end;
$$;

revoke all on function public.nm_auth_email_allowed(text, text) from public, anon, authenticated;
grant execute on function public.nm_auth_email_allowed(text, text) to service_role;
