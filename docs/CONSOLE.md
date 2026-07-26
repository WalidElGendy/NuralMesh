# Chat console rebuild

Replaces the beta chat at `/chat` — the agent sidebar, the personas behind it,
and the single blocking model call. Three things changed: what picks the
assistant's behaviour, how an answer is produced, and what the interface is.

Nothing about sign-in changes. The console uses the same `nm_access_token`
bearer contract as the `web/js/chat/` it replaces.

---

## 1. Why the answers were weak

Not a guess — this is what the code and the beta data actually show.

### The persona bug

```python
# agents.py v0.3
def resolve_persona(title):
    for key, prompt in AGENT_PERSONAS.items():
        if key in (title or "").strip().lower():   # substring match on the TITLE
            return prompt
```

`list_agents()` auto-seeded every user with seven threads named *Design Agent*,
*Content Agent*, *Sales Agent*, *Email Agent*, *Marketing Agent*, *Cowork
Agent*, *Personal Assistant Agent*. `resolve_persona()` then read the persona
back off whichever title the thread happened to have.

The consequence, from `public.messages`:

> **User:** حلل الأوضاع الاقتصاديه و الفرص في السوق السعودي
> **Assistant:** بصفتي مصمم وليس خبيرًا اقتصاديًا…

The thread's *name* had captured the answer. A question about the Saudi economy
was answered by a model instructed that it was a designer, which therefore
opened by declining to be an economist. The same mechanism made "Content Agent"
reply to `"hi"` with a four-question intake form instead of anything useful.

### The whitespace bug

Every stored assistant reply begins with six literal spaces —
`"      Hello! 👋"`. The system prompt was an indented Python literal and the
indentation went out on the wire. `mesh_prompts._t()` dedents and strips, so
this cannot recur.

### The silent-write bug

`agents.py` has always written `status`, `last_preview`, `unread_count` and
`pinned` to `conversations`. **None of those columns exist.** Every update
raised, was swallowed by `except Exception: logger.exception(...)`, and did
nothing. The evidence is unambiguous — across all 18 beta conversations:

```sql
select count(*) from conversations where updated_at <> created_at;  -- 0
```

No update has ever landed. That is why auto-generated titles never saved
(threads sit at "New chat"), why the sidebar preview is always empty, and why
the thread list cannot order by recency.

Migration `026` adds the columns. `_set_status()` now logs loudly instead of
swallowing, and the title write is isolated from the status write so one
failure cannot take the other down.

### No streaming, no telemetry

`_siliconflow_chat()` sent `"stream": False`, so a reply landed as one block
after a long silence. And `served_by` was NULL with `tokens`/`latency_ms` at 0
on **every** message row — a decentralised inference network keeping no record
of which node served anything.

---

## 2. What replaces it

### Modes, chosen deliberately

Behaviour comes from a control on the composer, not from a thread title.

| Mode | Pipeline | For |
|---|---|---|
| **Ask** | route → recall → draft | Direct answer, one call, under ~200 words |
| **Analyze** | + plan, + verify | Frame → decompose → quantify → interpret → stress-test |
| **Research** | + ground, + verify | Cited answers, conflicts reconciled explicitly |

Prompts live in `mesh_prompts.py`, server-side — they cannot drift from the
backend and are never shipped to the browser.

### A visible reasoning pipeline

```
route → recall → [plan | ground] → draft → verify
```

Each step is optional and the router decides, so `"hi"` costs one cheap call
while a research question costs four. Timings appear live in the strip above
each answer, and `trace` expands the router's decision, the plan, and what was
recalled.

- **route** — classifier (`/agents/complete`, task `route`): intent,
  complexity, needs-web, needs-memory, quantitative, language. Falls back to
  heuristics if the call fails.
- **recall** — keyword retrieval over the local knowledge graph and, if
  connected, the user's Obsidian vault. Client-side by design: note text goes
  nowhere until it is chosen as context for a turn.
- **plan** — decomposition into sub-questions with the quantities each needs.
- **ground** — `/api/search`, proxying Brave / Tavily / Serper so no key
  reaches the browser.
- **draft** — `/agents/{id}/turn/stream`, SSE.
- **verify** — adversarial self-check for fabrication, arithmetic, overclaim,
  non-answer and language drift. Shown, not hidden: a `verified 72%` chip plus
  an inline list of what it flagged.

### Provenance on every answer

Model or node, time-to-first-token, tokens/sec, token count, dollars saved
against a centralised provider, sources used, passages recalled, self-check
verdict. This is the differentiator — Grok and Kimi cannot show it.

It is also *honest*. The landing page says "Llama 3.3 70B on the sovereign GPU
mesh"; `agents.py` calls SiliconFlow with DeepSeek-V3.1. The chip reports what
actually served the turn, and the Mesh pane says "fallback active" when no
provider nodes are online. **Worth resolving that mismatch before launch.**

### Data renders as charts

Any set of numbers that varies across a dimension becomes an interactive
figure: hover tooltips, a legend that toggles series, a `table` view, and a
`pin` action collecting figures in the Analysis pane across threads. Markdown
tables are auto-charted when charting helps.

Hand-rolled SVG, no charting dependency, and a strict method:

- categorical hues in fixed slot order, never cycled
- palette validated against this surface —
  `"#3987e5,#d95926,#199e70,#c98500,#d55181,#008300"` on `#12151a`, all checks pass
- **one axis, always.** Incommensurable measures (a `%` column beside a `$`
  column) are split onto separate scales and offered as legend toggles rather
  than silently sharing a y-axis
- thin marks, 4px rounded data-ends on the baseline, 2px lines, 2px gap between
  adjacent fills, recessive grid
- table view and legend on every figure, so identity is never colour-alone

### Knowledge graph (the Obsidian model)

Concepts the assistant names are wrapped in `[[wiki-links]]` and become notes
with backlinks, tags and a force-directed graph view. This is what makes a
workspace compound — and it is what feeds `recall` on the next question.

Two layers:

1. **In-app graph** — every user gets it, persisted to `localStorage`.
2. **Vault bridge** — for people who keep an Obsidian vault. The browser talks
   to the *Local REST API* plugin on `127.0.0.1` directly, so **note content
   never reaches MeshNet servers**. Save a thread, append to the daily note,
   import the vault into the graph, search it as retrieval context.

No vault? Threads still export as Obsidian markdown with frontmatter, tags and
`[[links]]` intact.

### Interface

Rail → Threads → Conversation → Canvas (Analysis / Graph / Mesh / Vault).
Instrument-panel density: hairline grid, tabular numerals, monospace for data.
Turns are labelled records, not bubbles.

- `⌘K` command palette, `⌘B` threads, `⌘J` canvas, `⌘⇧O` new thread, `/` focus,
  `Esc` stop streaming
- light and dark are both *selected* palettes, not an inverted flip
- **RTL support** — the beta had none, so Arabic rendered left-to-right.
  Direction is detected per message and the layout uses logical properties
- below 780px the side panes become overlays instead of grid columns

---

## 3. Files

```
mesh_prompts.py            system prompts + modes (replaces AGENT_PERSONAS)
mesh_search.py             POST /api/search — Brave | Tavily | Serper proxy
mesh_status.py             GET  /api/mesh/status — aggregate node telemetry
agents.py                  v0.4: no personas, SSE turn, /complete, telemetry
migrations/026_*.sql       conversation state columns + turn telemetry
web/chat.html              shell + design tokens (inline CSS)
web/js/console/            native ES modules — no build step
  00-core.js                 config, helpers, icons, store, transport, RTL
  10-markdown.js             escape-first markdown, [[links]], #tags, tables
  20-charts.js               SVG charts, form heuristic, commensurability
  30-modes.js                client-side mode metadata
  40-engine.js               pipeline, SSE reader, cost model, threads client
  50-graph.js                knowledge graph + force simulation + recall
  55-vault.js                Obsidian Local REST API bridge
  60-shell.js                rail / threads / stage / canvas markup
  70-app.js                  turn rendering, streaming, events, boot
  99-entry.js                entry point
scripts/console-smoke.mjs  headless test against a stubbed API
```

`web/js/chat/` is left in place, untouched, so the old UI is one revert away.

---

## 4. Deploy

**Order matters.** Migration first, then the API, then the frontend.

```bash
# 1. database — without this, conversation state writes keep failing silently
psql "$DATABASE_URL" -f migrations/026_conversation_state_and_turn_telemetry.sql

# 2. API (Render/Railway) — new endpoints, no breaking changes to old ones
#    optional: BRAVE_API_KEY (or TAVILY_API_KEY / SERPER_API_KEY) for Research
#    optional: NM_PROVIDER_LABEL  — names what serves fallback traffic
#    optional: NM_HISTORY_CHARS   — context budget, default 24000

# 3. frontend — Vercel picks it up; the build step is unchanged
```

The frontend degrades on its own if step 2 lags: `/turn/stream` returning 404
falls back to the buffered `/turn`, a missing `/api/search` makes Research
answer from model knowledge and say so, and a missing `/api/mesh/status` shows
"telemetry off" rather than a fabricated node count.

### Rollback

One line in `web/chat.html`:

```html
<script type="module" src="/js/chat/main.js"></script>          <!-- old -->
<script type="module" src="/js/console/99-entry.js"></script>   <!-- new -->
```

`agents.py` v0.4 keeps every v0.3 endpoint and response shape, so the old
frontend still works against the new API. Set `NM_SEED_NAMED_AGENTS=1` to
restore the seven seeded threads if anything outside this repo depends on them.

---

## 5. Verification

```bash
npm i -D playwright && node scripts/console-smoke.mjs
```

Drives real Chromium against a stubbed API and asserts:

- welcome → Analyze turn → streamed answer → provenance chips
- charts from both a `mesh-chart` block and a markdown table
- knowledge graph layout, note list, `[[wiki-links]]` rendered
- the self-check verdict surfaced
- mesh telemetry pane, pin-to-Analysis, light theme
- Arabic input renders `dir="rtl"`
- the conversation still visible at 420px
- no agent-sidebar copy anywhere
- **zero console errors**

Screenshots land in `.console-shots/`.
