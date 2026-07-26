# Sovereign routing

The network exists so that GPU providers get paid by GPU users, with no
dependency on an outside LLM. Every token bought from SiliconFlow is cash
leaving that loop. This is how the code drives that number to zero.

---

## The policy

```
mesh can take it?  →  dispatch to a node      →  provider earns credits
mesh cannot?       →  buy it, record the reason →  platform pays cash
```

**There is no fixed 70/30 split, deliberately.** A fixed ratio does the wrong
thing in both directions: it keeps buying tokens after the mesh could have
served them, and it pushes traffic at the mesh before the mesh is ready. The
share is an *outcome* of live capacity, so it rises on its own as providers
join — no config change, no redeploy, no migration plan to execute.

`NM_MESH_MAX_SHARE` exists only to **cap** the mesh while canarying a new node
population. It is a ceiling, never a floor. Default `1.0` — use the mesh
whenever it can take the work, which is the intended steady state.

## Fail fast, not slow

A thin mesh must cost money, never user experience.

Each turn is offered to the mesh first, but only for `NM_DISPATCH_DEADLINE_S`
(default 4s). If no node claims the job in that window it is abandoned and the
turn falls back — **before a single token has been emitted**. The user sees a
slightly later first token, not a stall and not an error.

Once a node *has* claimed and started streaming, the lease keeps it: every
chunk it posts renews `lease_expires_at`. If it dies mid-answer the lease
lapses, `expire_stale_jobs()` reclaims the job, and the node takes a failure
mark. Three in a row trips a ten-minute circuit breaker.

## The reason codes are the roadmap

Every fallback is written to `routing_events` with one of:

| Reason | What it means | What to do |
|---|---|---|
| `no_nodes` | Nobody online | Recruit providers |
| `no_capacity` | Online, all busy | Recruit, or raise `max_concurrent` |
| `unhealthy` | Online but failing health gates | Support the providers you have |
| `model_unavailable` | Nobody serves the mesh model | Pin the model in onboarding |
| `unclaimed` | Online but too slow to pick jobs up | Tune node poll interval |
| `node_error` | Failed mid-answer | Investigate that node |
| `share_cap` | Throttled by config | Raise `NM_MESH_MAX_SHARE` |
| `disabled` | Mesh routing off | — |

```sql
select * from fallback_reasons_7d;
```

That is the provider-recruitment backlog, ordered by what each gap is costing
in real dollars. The Mesh pane renders it as "Why we bought tokens".

## The metric

```sql
select * from sovereignty_daily;
```

| column | meaning |
|---|---|
| `mesh_share` | tokens served by providers ÷ all tokens. **This is the number. Target 1.0** |
| `fallback_cost_usd` | cash paid to an outside LLM that day |
| `provider_credits` | earned by nodes that day |
| `top_fallback_reason` | the biggest thing standing between you and 1.0 |

The console shows `mesh_share` as the lead tile, the cost of not being
sovereign beside it, and the trend line under both. Every answer is labelled
**sovereign** (green, names the node) or **bought** (amber, names the provider
and the reason). No answer implies mesh provenance that did not happen.

---

## Why the queue was rebuilt

`api.py` has always exposed `/api/node/jobs/next`, `/complete` and `/error`
against a table called `jobs`.

```sql
select to_regclass('public.jobs');   -- null
```

That table does not exist. The mesh dispatch path has never executed once —
consistent with `providers` having rows while `provider_jobs` has none.
Migration 027 is the first working version, and it fixes three things the old
design would have hit immediately:

1. **No locking.** `select ... limit 1` then `update` let two pollers claim the
   same job. Now `claim_next_job()` does it in one statement with
   `FOR UPDATE SKIP LOCKED`.
2. **No lease.** A node that died mid-job stranded it in `processing` forever.
   Every claim now carries `lease_expires_at`, reaped every minute by pg_cron.
3. **No capacity or model awareness.** Any node got any job. Now the claim
   respects `max_concurrent`, `cooldown_until`, `accepts`, and the models the
   node actually advertises.

## Why pull, not push

GPU providers are home users behind NAT with no inbound ports. The API cannot
open a connection to them. So nodes poll `/api/node/jobs/next`, and stream
their output *back* by POSTing to `/api/node/jobs/{id}/chunk`, which the API
relays to the browser over SSE.

Requiring inbound connectivity would exclude exactly the consumer RTX cards the
network is built on. The chunk endpoint doubles as a liveness signal.

## Node contract

```
GET  /api/node/jobs/next
     → { job: { id, model, messages, params, lease_expires_at } }  or { job: null }

POST /api/node/jobs/{id}/chunk   { seq, content }     ← per token/segment, renews lease
POST /api/node/jobs/{id}/complete { output, model, prompt_tokens,
                                    completion_tokens, latency_ms }
POST /api/node/jobs/{id}/error    { error }
```

Poll on a short interval — a node that takes longer than
`NM_DISPATCH_DEADLINE_S` to claim work loses the job to the fallback and shows
up in `fallback_reasons_7d` as `unclaimed`.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `NM_MESH_MODEL` | `llama3.3:70b-instruct-q4_K_M` | What the mesh is being built to serve |
| `NM_MESH_ENABLED` | `1` | Kill switch |
| `NM_MESH_MAX_SHARE` | `1.0` | Ceiling for canarying. Never a floor |
| `NM_DISPATCH_DEADLINE_S` | `4` | How long a turn waits for a node before buying |
| `NM_LEASE_SECONDS` | `120` | Silence before a claimed job is reclaimed |
| `NM_MIN_SUCCESS_RATE` | `0.90` | Health gate |
| `NM_MAX_P95_MS` | `15000` | Health gate |
| `NM_HEARTBEAT_STALE_S` | `90` | Node considered gone |
| `NM_FALLBACK_USD_PER_MTOK` | `0.90` | What bought tokens cost you |
| `NM_MESH_CREDIT_PER_MTOK` | `0.89` | What providers earn |

## Rollout

```bash
psql "$DATABASE_URL" -f migrations/027_sovereign_routing.sql
# deploy API
```

Day one this changes nothing observable: with no eligible nodes the router
returns `fallback / no_nodes` on every turn and behaviour is identical to
today — except that you now have a number for what that costs. The first node
that comes online serving the mesh model starts moving `mesh_share` on its own.

To go back: `NM_MESH_ENABLED=0`. Routing reverts to fallback-only, the ledger
keeps recording, nothing else changes.

## The gap that is still open

`NM_MESH_CREDIT_PER_MTOK` (0.89) is what a provider earns. `plans.price_monthly`
is what a user pays. Nothing in the code reconciles those two into a margin, and
until it does, "providers get paid by users" is an intention rather than an
invariant. The ledger now has both sides on the same table — `credits` and
`cost_usd` per turn — so the reconciliation is a query away, but somebody has to
decide the take rate first.
