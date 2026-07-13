# EFund · Saudi Environment Fund

**Platform #1 on the MeshNet foundation.** → `ef.meshnet.co`

Fund, track and verify sustainability initiatives across the Kingdom — where **every milestone is
confirmed from orbit before a single riyal moves.**

Drop this directory into the `NuralMesh` monorepo root as `ef/`.

---

## The one idea

Most grant-oversight software asks the grantee to *report* progress. EFund asks the **satellite**.

Each milestone declares, up front, the imagery layer that will verify it. A disbursement cannot
be approved or paid against a milestone the imagery hasn't cleared — and that isn't a UI rule
that a determined user can route around. It's a Postgres trigger:

```
ERROR: Cannot release funds: milestone bdf9e518… is not satellite-verified
```

That single guarantee is the product. Everything else is scaffolding around it.

---

## Why it's sovereign (demonstrably, not rhetorically)

EFund runs **no AI of its own**. Every prompt goes to the MeshNet Smart Orchestrator, through the
7-stage pipeline (`classify → cache → prune → compress → route → verify → settle`), and is served
by a **GPU provider node**. The `done` SSE event returns `served_by` — the node that actually
executed the inference — and the UI prints it under every answer and every generated report.

So residency is *shown*, not asserted. Once Saudi GPU providers are attached to the mesh, you can
show a regulator which machine, inside which boundary, produced any given answer.

**This is the reusable pattern for the other 9 platforms: MeshNet is the compute and identity
spine; each platform contributes only its domain layer.**

```
                      MeshNet (foundation)
  Saudi GPU providers → Smart Orchestrator → Supabase (auth · billing · audit)
                              │
        ┌─────────────────────┼─────────────────────┐
   ef.meshnet.co        [platform 2]          [platform 3…10]
   EFund
```

---

## Data model (`ef` schema, PostGIS, isolated from MeshNet's `public` tables)

| Table | Purpose |
|---|---|
| `orgs`, `memberships` | Tenancy + RBAC (`viewer` / `analyst` / `operator` / `admin`) |
| `funds` | Capital under management |
| `initiatives` | **AOI as a first-class object** — geofence, grantee, budget, mandate, lifecycle |
| `milestones` | Each names its `verification_layer` — the claim and the check, declared together |
| `disbursements` | Gated by trigger on milestone verification |
| `kpis` | Every metric carries `source_layer`, `method`, `cadence`, `confidence` |
| `layers` | Data-fabric catalogue |
| `pois`, `alerts` | Field findings, rule-matched |
| `reports` | Analyst output, stamped with the `mesh_job_id` that produced it |
| `audit_log` | **Append-only** |

### The audit log genuinely cannot be rewritten

`ef.audit_log` has a `SELECT` policy and an `INSERT` policy — and **no `UPDATE` or `DELETE`
policy**. Under Postgres RLS, an absent policy means denied. `UPDATE`/`DELETE` are additionally
revoked from `anon` and `authenticated`. Not even an org admin can alter history.

---

## Run it

```bash
cd ef
cp .env.example .env.local     # fill in VITE_SUPABASE_ANON_KEY
npm install
npm run dev                    # → http://localhost:5180
```

| Var | Notes |
|---|---|
| `VITE_SUPABASE_URL` | `https://czphnagkzvkemgtkliew.supabase.co` |
| `VITE_SUPABASE_ANON_KEY` | Publishable anon key |
| `VITE_MESH_API_BASE` | `https://api.beta.meshnet.co` |
| `VITE_SENTINEL_HUB_INSTANCE_ID` | *Optional.* Unlocks NDVI / SAR / thermal. Free tier at [Sentinel Hub](https://apps.sentinel-hub.com/dashboard/). Without it, those layers are disabled in the UI rather than rendering broken tiles. |

**Keyless layers that work immediately:** OpenStreetMap · Sentinel-2 cloudless (EOX) · Esri World
Imagery · AWS Terrain (DSM).

### Grant yourself access

RLS means a signed-in user with no membership row sees **nothing** — by design. After creating
your Supabase auth user:

```sql
insert into ef.memberships (org_id, user_id, role)
select o.id, u.id, 'admin'
from ef.orgs o, auth.users u
where o.name like 'MEWA%' and u.email = 'you@example.com';
```

Seeded: **Wadi Ad-Dawasir Aquifer Watch** (3 milestones — one verified and paid, one in review,
one pending) and **NEOM Solar Farm — Sector 7**.

---

## Launch to `ef.meshnet.co`

1. **Vercel → Add New Project** → import the `NuralMesh` repo.
2. **Root Directory: `ef`** ← the important one. Framework preset auto-detects as Vite.
3. **Environment Variables** — add the four from the table above.
4. **Deploy.**
5. **Settings → Domains → Add `ef.meshnet.co`.**
6. **DNS** — add the record Vercel shows you:
   `CNAME  ef  →  cname.vercel-dns.com`
7. **Supabase → Authentication → URL Configuration** — add `https://ef.meshnet.co` to
   **Redirect URLs** and set it as a **Site URL**, or sign-in will bounce.
8. **CORS** — add `https://ef.meshnet.co` to `ALLOWED_ORIGINS` on the Render API service, or the
   browser will block every call to the orchestrator.

`vercel.json` already handles SPA rewrites, `/api/*` → orchestrator, HSTS, and
`X-Frame-Options: DENY`.

---

## Status

| | |
|---|---|
| ✅ | `ef` schema, PostGIS, RLS on all 12 tables |
| ✅ | Milestone → satellite verification → disbursement, enforced by DB trigger |
| ✅ | Portfolio overview, initiatives, initiative detail with ledger |
| ✅ | Earth Intelligence map — AOI drawing, live layer stack |
| ✅ | Ask — AOI-grounded chat via MeshNet, with `served_by` residency proof |
| ✅ | Reports — analyst agents on MeshNet, archived with mesh job id |
| ✅ | Invite gate, Supabase auth, RBAC, append-only audit trail |
| ✅ | EN / AR |
| ◻︎ | Automated verification job (currently milestones are marked verified by an analyst) |
| ◻︎ | Imagery tasking pipeline — **contract-gated**, see below |

## One thing to be straight with buyers about

The tasking pipeline in the capability brief (Pending → Queued → Acquiring → Processed → Ready,
8–24h revisit) is not a software problem. It requires commercial contracts with Planet, ICEYE,
Airbus or similar. Sentinel gives you a free 5-day revisit and that is genuinely enough to
demonstrate the verification loop — but VHR and SAR tasking is contract-gated, and promising it
before those contracts exist is the fastest way to lose a government account.
