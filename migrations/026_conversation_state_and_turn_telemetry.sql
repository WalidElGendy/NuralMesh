-- Migration 026: repair conversation state, and record turn telemetry
--
-- WHY THIS EXISTS
--
-- `agents.py` has always written these columns:
--
--     supabase.table("conversations").update({
--         "status": "running", "last_preview": ...           -- agent_turn()
--     })
--     supabase.table("conversations").update({
--         "status": "idle", "last_preview": ..., "title": auto_title
--     })
--
-- None of them exist on `conversations`. Every one of those updates raised,
-- was swallowed by `except Exception: logger.exception(...)`, and silently
-- did nothing. The evidence is in the data: across all 18 beta conversations
-- `updated_at = created_at` exactly — no update has ever landed. That is why
--
--   * auto-generated titles never saved (threads stay "New chat"),
--   * `last_preview` is always null in the sidebar,
--   * the thread list cannot order by recency, because updated_at never moves,
--   * `status` never reflects a running turn, so there is no typing state.
--
-- The application code's intent was right; the schema was missing. This adds
-- the columns rather than removing the writes.
--
-- It also adds per-turn telemetry to `messages`. The beta wrote served_by
-- NULL and tokens/latency_ms 0 on every row, which made the inference network
-- invisible inside its own product.

-- ---------------------------------------------------------------------------
-- conversations: the state agents.py already tries to write
-- ---------------------------------------------------------------------------

alter table conversations
  add column if not exists status        text    not null default 'idle',
  add column if not exists last_preview  text,
  add column if not exists unread_count  integer not null default 0,
  add column if not exists pinned        boolean not null default false,
  add column if not exists mode          text;

alter table conversations
  drop constraint if exists conversations_status_check;
alter table conversations
  add constraint conversations_status_check
  check (status in ('idle', 'running', 'error'));

comment on column conversations.status is
  'idle | running | error. Set to running while a turn is in flight so the UI
   can show live state on threads other than the open one.';
comment on column conversations.mode is
  'ask | analyze | research — the answer mode this thread was last used with.';

create index if not exists conversations_user_updated_idx
  on conversations (user_id, updated_at desc)
  where deleted_at is null;

-- ---------------------------------------------------------------------------
-- keep updated_at honest
--
-- agents.py relies on updated_at for thread ordering but never sets it. Do it
-- in the database so it cannot be forgotten by any client.
-- ---------------------------------------------------------------------------

create or replace function touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists conversations_touch on conversations;
create trigger conversations_touch
  before update on conversations
  for each row execute function touch_updated_at();

create or replace function touch_conversation_from_message()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  update conversations
     set updated_at   = now(),
         last_preview = left(new.content, 120)
   where id = new.conversation_id;
  return new;
end;
$$;

drop trigger if exists messages_touch_conversation on messages;
create trigger messages_touch_conversation
  after insert on messages
  for each row execute function touch_conversation_from_message();

-- ---------------------------------------------------------------------------
-- messages: per-turn telemetry
-- ---------------------------------------------------------------------------

alter table messages
  add column if not exists mode  text,
  add column if not exists meta  jsonb not null default '{}'::jsonb;

comment on column messages.served_by is
  'Node id that served this turn, or the upstream provider name for fallback
   traffic. NULL means the server did not report provenance — a bug, not an
   absence.';
comment on column messages.meta is
  'Per-turn record: model, route decision, step timings, sources, self-check.';

create index if not exists messages_conversation_created_idx
  on messages (conversation_id, created_at);

-- ---------------------------------------------------------------------------
-- backfill: give existing threads a usable preview and ordering
-- ---------------------------------------------------------------------------

update conversations c
   set last_preview = sub.content,
       updated_at   = sub.created_at
  from (
    select distinct on (conversation_id)
           conversation_id, left(content, 120) as content, created_at
      from messages
     order by conversation_id, created_at desc
  ) sub
 where sub.conversation_id = c.id
   and c.last_preview is null;
