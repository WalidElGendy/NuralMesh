-- Migration 025: add intent + email to invites for automated waitlist emails
-- Lets each auto-generated activation code record who it was issued to and which flow.

alter table invites add column if not exists intent text;
alter table invites add column if not exists email text;

-- 'user' (AI user) or 'provider' (GPU provider); null for legacy/admin-generated codes.
alter table invites
  add constraint invites_intent_check
  check (intent is null or intent in ('user', 'provider'));

create index if not exists invites_email_idx on invites (email);
create index if not exists invites_intent_idx on invites (intent);
