# ADR 0024: Multi-agent sidebar UX for beta.meshnet.co/chat.html

- Status: Accepted
- Date: 2026-05-17
- Owner: @WalidElGendy
- Related: ADR 0020 (beta launch architecture), ADR 0022 (provider installer), ADR 0023 (payout manual cap)

## Context

The pre-launch chat.html was a single textarea that POSTed to `/api/chat` and rendered a single response inline.
Beta users want to drive multiple long-running tasks in parallel without losing context when switching between them,
and they expect to close the tab and return to find every conversation intact. The reference mental model is WhatsApp:
a left sidebar listing chats, one chat = one persistent conversation, switching chats does not pause the others.

## Decision

We replace the chat page with a two-pane layout: a fixed-width sidebar (collapsible to icon-only at <=72px) listing every
"agent" (one row per persistent conversation) and a right pane showing the selected agent's message log + composer.
Each agent maps 1:1 to a row in the new `conversations` table; each message maps 1:1 to a row in `messages`. Multiple
agents are allowed to run server-side turns in parallel; switching the active agent in the UI does not interrupt them.

### Scope guardrails

- `MAX_CONCURRENT_AGENTS_PER_USER = 5` (enforced server-side in `agents.py`). Beyond this cap the create endpoint returns
  HTTP 429 with a structured `{detail: "max_agents_reached", limit: 5}` body so the sidebar can render an inline upsell.
- Auto-title generation uses a single cheap Llama 3.1 8B call after the first user turn; the auto-title is best-effort
  and never blocks the conversation reply. Failures fall back to the literal first 40 chars of the user message.
- Unread badges + tab-title prefix `(N) NeuralMesh Beta` are pure client state derived from `last_read_at` on each agent.

### Schema (migration 024_conversations_and_messages.sql)

- `public.conversations(id uuid pk, user_id uuid, title text, status text default 'active', created_at, updated_at, last_message_at, last_read_at)`
- `public.messages(id uuid pk, conversation_id uuid fk, role text check in ('user','assistant','system'), content text, tokens_in int, tokens_out int, created_at)`
- RLS policy: `user_id = auth.uid()` on conversations; messages joined via conversation_id.
- Indexes: `messages(conversation_id, created_at)`, `conversations(user_id, last_message_at desc)`.

### API surface (agents.py)

- `GET /api/agents` -> list current user's conversations, ordered by `last_message_at desc`.
- `POST /api/agents` -> create a new conversation (enforces MAX_CONCURRENT_AGENTS_PER_USER).
- `PATCH /api/agents/{id}` -> rename (`title`) or update `last_read_at`.
- `DELETE /api/agents/{id}` -> soft-delete (status = 'archived') so message history is recoverable.
- `GET /api/agents/{id}/messages` -> paginated message log for the selected agent.
- `POST /api/agents/{id}/turn` -> append a user message, dispatch to the existing `/api/chat` worker, persist the assistant reply.
- All endpoints require `Authorization: Bearer <supabase-jwt>`; missing/invalid token yields 401 with `{detail: "missing_bearer_token"}`.

### Frontend architecture

Vanilla JS ES modules under `web/js/chat/` with a handwritten 80-line pub/sub store. No build step, no framework. Why:
- The repo is single-developer and Render/Vercel already deploy static `web/` directly; adding a build step would add CI complexity for negligible payoff at this scale.
- The full sidebar + pane + composer interaction surface is small (~7 modules, ~16 KB unminified) and easy to read end-to-end.
- Browser-native modules + Fetch + CustomEvent cover every required behavior; the store is the only piece of plumbing.

Module breakdown:

| Module | Responsibility |
|---|---|
| `main.js` | Boot: instantiate store, wire api+sidebar+conversation+composer, restore active agent from localStorage, kick `loadAgents()`. |
| `store.js` | Pub/sub state (agents map, activeId, unreadCounts, typingByAgent). |
| `api.js` | REST wrapper with `Authorization: Bearer ${nm_access_token}`; redirects to /login.html on 401. |
| `sidebar.js` | Renders agent list, search (Cmd+K), new-agent button (Cmd+N), right-click rename/cancel/delete menu, arrow-key navigation. |
| `conversation.js` | Pane header (title + status), message bubbles, typing indicator, optimistic message rendering. |
| `composer.js` | Auto-growing textarea + send button + Enter-to-send / Shift+Enter newline. |
| `notifications.js` | Updates document.title with `(N) NeuralMesh Beta` and plays a -18 dB blip on incoming assistant message when the agent is not active. |

### Auth model

The existing `/api/auth/login` endpoint already returns `{access_token, refresh_token, expires_at, user_id, email}` in the JSON body alongside its `Set-Cookie`.
We stash `access_token` to `localStorage['nm_access_token']` from `login.html`. The chat modules read that key and attach `Authorization: Bearer <token>` to every `/api/*` call.
Cookies continue to handle other auth flows untouched.

## Consequences

Positive:
- Users can run up to 5 long-running tasks in parallel and switch between them instantly.
- Closing/reopening the tab restores state from the server, not from fragile sessionStorage snapshots.
- The vanilla-JS module split keeps each file small enough to read in one screen and test in isolation.

Negative / future work:
- No realtime push yet: typing indicators and unread counts poll every 4s. A Supabase Realtime channel is the natural follow-up.
- Auto-title via Llama 3.1 8B adds ~80ms latency to the first turn; mitigated by running it in a fire-and-forget background task.
- `MAX_CONCURRENT_AGENTS_PER_USER = 5` is a guess; revisit after the first 100 beta users.
- The handwritten store has no time-travel debugging; if state bugs become common we revisit by porting to Preact Signals (3 KB) without changing the module boundaries.

## Rollout

1. Apply `migrations/024_conversations_and_messages.sql` against Supabase prod.
2. Render auto-deploys `agents.py` + `api.py` wire-in (already merged to main).
3. Vercel auto-deploys the new `web/chat.html` shell + `web/js/chat/*` modules + `web/login.html` token-persist patch.
4. Manual smoke test: log in, create 2 agents in different tabs, send a turn in each, refresh, confirm both restore.
5. Set `NM_TEST_TOKEN` in CI to enable `tests/test_agents_crud.py` against staging.

