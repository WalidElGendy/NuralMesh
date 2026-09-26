/* ==========================================================================
   Agents — a gallery of purpose-built assistants, bound to a thread.

   HISTORY / WHY THIS IS SAFE
   --------------------------
   v0.3 shipped "personas" that were removed on purpose (see 30-modes.js and
   mesh_prompts.py): resolve_persona() picked a system prompt by SUBSTRING-
   MATCHING THE THREAD TITLE, and every user was auto-seeded seven persona
   threads. A thread's *name* then silently dictated how every answer in it was
   written — an economics question in a "Design Agent" thread came back as
   "as a designer, not an economist".

   This is the opposite design and does not reintroduce that bug:
     · An agent is chosen EXPLICITLY by the user from this gallery, never
       inferred from a title.
     · The binding is a stable SLUG (e.g. "email"), stored per-thread, and sent
       verbatim with every turn as context.agent_type. The title is free to
       change (auto-title, rename) without ever changing behaviour.
     · The agent's actual instructions live SERVER-SIDE in agents.py, keyed by
       that slug — the browser only knows display copy. Prompts cannot drift or
       leak, exactly as the modes do.
     · Agents are ADDITIVE specialisation layered on the base identity: they
       never refuse an out-of-scope question and never demand requirements
       before answering (the two failures that made the old personas feel
       broken). That contract is enforced in the server prompts.

   Every turn still routes through the same engine: mesh (Ollama on the GPU
   nodes) first, paid provider only on fallback. An agent shapes the answer; it
   does not change where the tokens come from.
   ========================================================================== */

import { S, $, $$, esc, emit, toast } from './00-core.js';
import { threads as threadsApi } from './40-engine.js';

/* ------------------------------- catalogue ------------------------------- */
/* Display copy only. The behaviour for each slug lives in agents.py.
   `integrations` are scaffolded connect-points — wired in the UI, not yet
   live — so the product is ready to plug real OAuth into later. */

export const AGENTS = [
  {
    slug: 'email', name: 'Email & Calendar', emoji: '📧', mode: 'ask',
    blurb: 'Triage the inbox, draft replies in your voice, and turn messages into calendar events.',
    integrations: ['Gmail', 'Outlook', 'Google Calendar'],
    suggested: [
      { t: 'Draft a reply', q: 'Draft a warm, concise reply agreeing to the meeting and proposing Tuesday or Thursday afternoon.' },
      { t: 'Summarise a thread', q: 'Summarise this email thread into decisions made, open questions, and who owes what by when.' },
      { t: 'Plan my week', q: 'Given these commitments, propose a calendar for next week that protects two deep-work blocks a day.' },
    ],
  },
  {
    slug: 'tasks', name: 'Reminders & Tasks', emoji: '✅', mode: 'ask',
    blurb: 'Capture to-dos and deadlines, chase follow-ups, and turn a messy brain-dump into a plan.',
    integrations: ['Apple Reminders', 'Todoist', 'Google Tasks'],
    suggested: [
      { t: 'Sort a brain-dump', q: 'Turn this brain-dump into a prioritised task list with due dates and the single most important next action.' },
      { t: 'Follow-ups', q: 'List the follow-ups I owe people this week and draft a one-line nudge for each.' },
      { t: 'Daily plan', q: 'Build a realistic plan for today from these tasks, time-boxed, hardest thing first.' },
    ],
  },
  {
    slug: 'travel', name: 'Bookings & Trips', emoji: '✈️', mode: 'ask',
    blurb: 'Plan trips end to end — flights, hotels, itineraries, visas and a running budget.',
    integrations: ['Gmail (confirmations)', 'Google Calendar', 'Google Flights'],
    suggested: [
      { t: 'Plan a trip', q: 'Plan a 4-day trip to Istanbul in October for two: neighbourhoods to stay in, a day-by-day itinerary, and a rough budget.' },
      { t: 'Compare options', q: 'Compare taking the train vs flying from Jeddah to Riyadh on time, cost and hassle.' },
      { t: 'Packing list', q: 'Make a packing list for a 5-day business trip with two formal dinners and one desert excursion.' },
    ],
  },
  {
    slug: 'notes', name: 'Notes', emoji: '📝', mode: 'ask',
    blurb: 'Capture, summarise and organise notes and meeting minutes you can actually find later.',
    integrations: ['Obsidian', 'Notion', 'Apple Notes'],
    suggested: [
      { t: 'Meeting minutes', q: 'Turn these raw meeting notes into clean minutes: decisions, action items with owners, and next steps.' },
      { t: 'Summarise', q: 'Summarise this long note into five bullet points and a one-line takeaway.' },
      { t: 'Organise', q: 'Group these scattered notes into themes and suggest a folder structure with [[links]].' },
    ],
  },
  {
    slug: 'marketing', name: 'Marketing', emoji: '📣', mode: 'ask',
    blurb: 'Campaigns, copy, social posts, content calendars and positioning that sound like you.',
    integrations: ['Buffer', 'Mailchimp', 'X / LinkedIn'],
    suggested: [
      { t: 'Launch copy', q: 'Write launch copy for a one-click GPU node installer: a headline, three benefit bullets, and a CTA.' },
      { t: 'Content calendar', q: 'Draft a two-week social content calendar for a developer audience, 3 posts a week, with hooks.' },
      { t: 'Positioning', q: 'Sharpen the positioning for a sovereign AI mesh against centralised providers in three sentences.' },
    ],
  },
  {
    slug: 'sales', name: 'Sales & CRM', emoji: '💼', mode: 'ask',
    blurb: 'Work leads, personalise outreach, handle objections and keep the pipeline moving.',
    integrations: ['HubSpot', 'Salesforce', 'Gmail'],
    suggested: [
      { t: 'Cold outreach', q: 'Write a short, specific cold email to a fintech CTO about cutting inference cost with a GPU mesh.' },
      { t: 'Handle an objection', q: 'The prospect says "we already use OpenAI and it works fine." Give me three ways to respond.' },
      { t: 'Follow-up cadence', q: 'Design a 5-touch follow-up cadence over two weeks after a demo, with the message for each touch.' },
    ],
  },
  {
    slug: 'research', name: 'Research', emoji: '🔎', mode: 'research',
    blurb: 'Deep research with citations — market scans, competitor teardowns, reconcile conflicts.',
    integrations: ['Live web', 'PDF upload', 'Google Scholar'],
    suggested: [
      { t: 'Market scan', q: 'Scan the current market for decentralised GPU / inference networks: who the players are and how they price. Cite sources.' },
      { t: 'Competitor teardown', q: 'Tear down the pricing and positioning of the three biggest inference providers right now, with citations.' },
      { t: 'Fact-check', q: 'Fact-check this claim with sources and tell me how confident I should be.' },
    ],
  },
  {
    slug: 'docs', name: 'Documents & Contracts', emoji: '📄', mode: 'ask',
    blurb: 'Draft and review documents, contracts, policies and proposals — with plain-English redlines.',
    integrations: ['Google Drive', 'Google Docs', 'PDF upload'],
    suggested: [
      { t: 'Draft a proposal', q: 'Draft a one-page proposal to run a paid pilot of a GPU node program with a mid-size studio.' },
      { t: 'Review a contract', q: 'Review this contract clause for risks to me and suggest safer wording in plain English.' },
      { t: 'Write a policy', q: 'Write a short acceptable-use policy for a beta AI product, friendly but clear.' },
    ],
  },
  {
    slug: 'finance', name: 'Finance & Invoices', emoji: '💳', mode: 'analyze',
    blurb: 'Invoices, quotes, expenses, budgets and cashflow — with the arithmetic shown.',
    integrations: ['Stripe', 'QuickBooks', 'Xero'],
    suggested: [
      { t: 'Build an invoice', q: 'Draft an invoice for 3 consulting days at $600/day plus 15% VAT, with a clean line-item breakdown.' },
      { t: 'Quote a job', q: 'Help me quote a fixed-price website build: estimate the hours, add a buffer, and show the maths.' },
      { t: 'Cashflow', q: 'Given these monthly revenues and costs, project my cashflow for the next 6 months and flag the tight month.' },
    ],
  },
  {
    slug: 'support', name: 'Support', emoji: '🎧', mode: 'ask',
    blurb: 'Customer replies, FAQs, saved macros and ticket triage — fast, on-brand and kind.',
    integrations: ['Zendesk', 'Intercom', 'Gmail'],
    suggested: [
      { t: 'Reply to a ticket', q: 'Write a friendly reply to a customer whose installer hit a SmartScreen warning, with the exact fix steps.' },
      { t: 'Write an FAQ', q: 'Turn these five recurring questions into a clean FAQ with short answers.' },
      { t: 'Draft macros', q: 'Draft three reusable support macros: refund approved, bug acknowledged, and feature requested.' },
    ],
  },
  {
    slug: 'data', name: 'Data & Analysis', emoji: '📊', mode: 'analyze',
    blurb: 'Spreadsheets, metrics, forecasts and charts you can pin — every estimate labelled.',
    integrations: ['Google Sheets', 'CSV upload', 'PostgreSQL'],
    suggested: [
      { t: 'Analyse a funnel', q: 'From 258 invites, 38 signups and 18 activations, work out the conversion at each step and the biggest drop-off.' },
      { t: 'Forecast', q: 'Given the last 6 months of revenue, forecast the next 3 and chart it, stating the assumption.' },
      { t: 'Explain a metric', q: 'Explain what a good weekly retention curve looks like and how to read cohort tables.' },
    ],
  },
  {
    slug: 'assistant', name: 'Personal Assistant', emoji: '🧭', mode: 'ask',
    blurb: 'Your everyday concierge — a daily brief, quick answers, and it points you to the right agent.',
    integrations: ['Gmail', 'Google Calendar', 'Contacts'],
    suggested: [
      { t: 'Daily brief', q: 'Give me a short morning brief: what matters today, what to prioritise, and one thing not to forget.' },
      { t: 'Quick decision', q: 'Help me decide between two options by laying out the trade-offs and giving a clear recommendation.' },
      { t: 'Which agent?', q: 'I need to plan a product launch. Which of the agents should I use and in what order?' },
    ],
  },
];

const BY_SLUG = Object.fromEntries(AGENTS.map(a => [a.slug, a]));
export const agentMeta = (slug) => BY_SLUG[slug] || null;

/* ---------------------------- thread bindings ---------------------------- */
/* Per-thread agent slug. Persisted client-side so a bound thread keeps its
   agent across reloads. The slug also travels with every turn, so the server
   applies the right prompt even if this map is ever empty. */

const BIND_KEY = 'mesh.agentByThread';
let bindings = {};
try { bindings = JSON.parse(localStorage.getItem(BIND_KEY) || '{}') || {}; } catch { bindings = {}; }

export function agentForThread(id) { return (id && bindings[id]) || null; }
export function isAgentThread(id) { return !!agentForThread(id); }

function bindAgent(id, slug) {
  bindings[id] = slug;
  try { localStorage.setItem(BIND_KEY, JSON.stringify(bindings)); } catch {}
}

/* ------------------------------- agent icon ------------------------------ */

const GRID_ICON = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/>
  <rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>`;

/* -------------------------------- styling -------------------------------- */

function injectStyles() {
  if ($('#agentStyles')) return;
  const css = `
  .ascrim{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:72;display:grid;
    place-items:start center;padding:6vh 16px 16px;overflow-y:auto}
  .ascrim[hidden]{display:none}
  .apanel{width:min(1040px,100%);background:var(--s-1);border:1px solid var(--line-2);
    border-radius:var(--r-lg);box-shadow:0 24px 70px rgba(0,0,0,.6);overflow:hidden}
  .apanel__head{display:flex;align-items:center;gap:10px;padding:16px 18px;border-bottom:1px solid var(--line)}
  .apanel__title{font-size:15px;font-weight:600}
  .apanel__sub{font-family:var(--mono);font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3)}
  .apanel__x{margin-inline-start:auto;width:30px;height:30px;border-radius:var(--r-sm);display:grid;place-items:center;color:var(--ink-3)}
  .apanel__x:hover{background:var(--s-3);color:var(--ink-1)}
  .agrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(228px,1fr));gap:12px;padding:16px}
  .acard{display:grid;gap:8px;text-align:start;padding:14px;border:1px solid var(--line);
    border-radius:var(--r-md);background:var(--s-0);transition:border-color .15s,transform .08s}
  .acard:hover{border-color:var(--accent);transform:translateY(-1px)}
  .acard__top{display:flex;align-items:center;gap:10px}
  .acard__ico{width:34px;height:34px;border-radius:9px;display:grid;place-items:center;font-size:18px;
    background:var(--s-2);border:1px solid var(--ring);flex:none}
  .acard__name{font-size:13.5px;font-weight:600;color:var(--ink-1)}
  .acard__blurb{font-size:12.5px;color:var(--ink-3);line-height:1.5}
  .acard__ints{display:flex;flex-wrap:wrap;gap:4px;margin-top:2px}
  .acard__int{font-family:var(--mono);font-size:9.5px;padding:1px 5px;border-radius:3px;
    background:var(--s-2);color:var(--ink-4);border:1px solid var(--line)}
  /* agent welcome inside the stream */
  .awelcome{display:grid;gap:18px;padding-top:26px}
  .awelcome__id{display:flex;align-items:center;gap:12px}
  .awelcome__ico{width:44px;height:44px;border-radius:11px;display:grid;place-items:center;font-size:24px;
    background:var(--s-2);border:1px solid var(--ring)}
  .awelcome h1{font-size:22px;font-weight:600;letter-spacing:-.02em}
  .awelcome__blurb{color:var(--ink-3);font-size:14px;max-width:60ch}
  .aconnect{border:1px solid var(--line);border-radius:var(--r-md);background:var(--s-1);padding:12px 14px;display:grid;gap:9px}
  .aconnect__k{font-family:var(--mono);font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-4)}
  .aconnect__row{display:flex;flex-wrap:wrap;gap:8px}
  .aint{display:inline-flex;align-items:center;gap:7px;height:30px;padding:0 11px;border-radius:var(--r-sm);
    border:1px solid var(--line-2);background:var(--s-0);color:var(--ink-2);font-size:12.5px}
  .aint:hover{border-color:var(--accent);color:var(--ink-1)}
  .aint__soon{font-family:var(--mono);font-size:9px;letter-spacing:.05em;text-transform:uppercase;color:var(--ink-4)}
  @media (max-width:640px){ .agrid{grid-template-columns:1fr 1fr} .acard__blurb{display:none} }
  @media (max-width:440px){ .agrid{grid-template-columns:1fr} }`;
  const el = document.createElement('style');
  el.id = 'agentStyles';
  el.textContent = css;
  document.head.appendChild(el);
}

/* --------------------------------- rail ---------------------------------- */

function injectRailButton() {
  const rail = $('.rail');
  if (!rail || $('#agentsBtn')) return;
  const btn = document.createElement('button');
  btn.className = 'rbtn';
  btn.id = 'agentsBtn';
  btn.title = 'Agents';
  btn.innerHTML = GRID_ICON;
  const spacer = rail.querySelector('.rail__spacer');
  rail.insertBefore(btn, spacer || null);
}

/* ------------------------------- gallery --------------------------------- */

function buildScrim() {
  if ($('#agentScrim')) return;
  const scrim = document.createElement('div');
  scrim.className = 'ascrim';
  scrim.id = 'agentScrim';
  scrim.hidden = true;
  scrim.innerHTML = `
    <div class="apanel" role="dialog" aria-label="Agents">
      <div class="apanel__head">
        <span class="apanel__title">Agents</span>
        <span class="apanel__sub">on the mesh · Ollama</span>
        <button class="apanel__x" id="agentScrimX" aria-label="Close">✕</button>
      </div>
      <div class="agrid" id="agentGrid">
        ${AGENTS.map(a => `
          <button class="acard" data-agent-card="${esc(a.slug)}">
            <span class="acard__top">
              <span class="acard__ico" aria-hidden="true">${a.emoji}</span>
              <span class="acard__name">${esc(a.name)}</span>
            </span>
            <span class="acard__blurb">${esc(a.blurb)}</span>
            <span class="acard__ints">${a.integrations.map(i => `<span class="acard__int">${esc(i)}</span>`).join('')}</span>
          </button>`).join('')}
      </div>
    </div>`;
  document.body.appendChild(scrim);
}

export function openAgentGallery() { buildScrim(); const s = $('#agentScrim'); if (s) s.hidden = false; }
export function closeAgentGallery() { const s = $('#agentScrim'); if (s) s.hidden = true; }

/* ------------------------ agent welcome (in stream) ---------------------- */

export function agentWelcomeHTML(slug) {
  const a = agentMeta(slug);
  if (!a) return '';
  return `
  <div class="awelcome">
    <div class="awelcome__id">
      <span class="awelcome__ico" aria-hidden="true">${a.emoji}</span>
      <div>
        <h1>${esc(a.name)}</h1>
        <p class="awelcome__blurb">${esc(a.blurb)}</p>
      </div>
    </div>
    <div class="aconnect">
      <span class="aconnect__k">Connect your accounts</span>
      <div class="aconnect__row">
        ${a.integrations.map(i => `
          <button class="aint" data-int="${esc(i)}">${esc(i)}<span class="aint__soon">soon</span></button>`).join('')}
      </div>
    </div>
    <div style="display:grid;gap:8px">
      ${a.suggested.map(s => `
        <button class="thread" data-starter="${esc(s.q)}" data-starter-mode="${esc(a.mode)}"
                style="border:1px solid var(--line);background:var(--s-1);padding:11px 13px">
          <span style="display:flex;align-items:center;gap:8px">
            <span class="tag">${esc(a.mode)}</span>
            <span class="thread__t" style="font-weight:550;color:var(--ink-1)">${esc(s.t)}</span>
          </span>
          <span class="thread__m" style="white-space:normal">${esc(s.q.slice(0, 116))}…</span>
        </button>`).join('')}
    </div>
  </div>`;
}

/* --------------------------------- wiring -------------------------------- */

async function openAgent(slug) {
  const a = agentMeta(slug);
  if (!a) return;
  let row;
  try {
    row = await threadsApi.create(a.name);
  } catch (e) {
    toast('Could not start this agent: ' + e.message, 'err');
    return;
  }
  bindAgent(row.id, slug);
  S.threads.unshift({ ...row, n: 0, tags: [], agent: slug });
  closeAgentGallery();
  // 70-app owns the stream + thread state; hand off through the event bus so we
  // avoid a circular import.
  emit('agent:open', { id: row.id, slug, mode: a.mode });
}

export function initAgents() {
  injectStyles();
  injectRailButton();
  buildScrim();

  document.addEventListener('click', (e) => {
    const railBtn = e.target.closest('#agentsBtn');
    if (railBtn) { openAgentGallery(); return; }

    const card = e.target.closest('[data-agent-card]');
    if (card) { openAgent(card.dataset.agentCard); return; }

    if (e.target.closest('#agentScrimX')) { closeAgentGallery(); return; }
    const scrim = e.target.closest('#agentScrim');
    if (scrim && e.target === scrim) { closeAgentGallery(); return; }

    const intBtn = e.target.closest('[data-int]');
    if (intBtn) {
      toast(`${intBtn.dataset.int} integration is coming soon — the agent works now, this just connects your account.`);
      return;
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeAgentGallery();
  });
}
