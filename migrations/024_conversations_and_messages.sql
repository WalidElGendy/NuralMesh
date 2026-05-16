-- 024_conversations_and_messages.sql
-- Creates the agents/conversations + messages tables for the multi-agent chat UI.
-- This is idempotent and additive. Safe to re-run.

create extension if not exists pgcrypto;

create table if not exists conversations (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    title text,
    status text not null default 'idle'
        check (status in ('idle','running','error','cancelled')),
    last_preview text,
    unread_count integer not null default 0,
    pinned boolean not null default false,
    current_job_id uuid,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deleted_at timestamptz
);

create index if not exists idx_conversations_user_updated
    on conversations(user_id, updated_at desc)
    where deleted_at is null;

create table if not exists messages (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references conversations(id) on delete cascade,
    role text not null check (role in ('user','assistant','system')),
    content text not null,
    created_at timestamptz not null default now()
);

create index if not exists idx_messages_conv_created
    on messages(conversation_id, created_at asc);

create or replace function touch_conversation_updated_at() returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_conversations_touch on conversations;
create trigger trg_conversations_touch
  before update on conversations
  for each row execute function touch_conversation_updated_at();
