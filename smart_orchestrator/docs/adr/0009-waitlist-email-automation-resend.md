# ADR 0009  Waitlist Email Automation via Resend

**Status:** Accepted  
**Date:** 2025-05-03

## Context
When a user or provider joins the waitlist, they should get a welcome email immediately.

## Decision
**Trigger mechanism:** Supabase Database Webhook (not pg_net trigger).

**Trade-offs:**
| Option | Pro | Con |
|---|---|---|
| Supabase DB Webhook | Visual config in dashboard, easy debug | Requires Supabase Pro ($25/mo) |
| pg_net trigger | Free tier, in-database logic | Harder to debug, requires pg_net extension |

We chose Supabase DB Webhook because:
1. Easier to set up without SQL function expertise
2. Webhook logs are visible in Supabase dashboard
3. Works immediately without schema changes

SQL for pg_net trigger is preserved as comments in `migrations/005_waitlist_email_trigger.sql` for free-tier fallback.

**Email provider:** Resend (resend.com)  free tier = 3,000 emails/month.
- Single function: `send_email(to, subject, html)`
- No-ops gracefully if `RESEND_API_KEY` not set (local dev)
- Protected endpoint: `POST /internal/notify-waitlist` requires `X-Internal-Key` header

## Consequences
+ Zero emails lost (Supabase webhook retries on failure)
+ Email templates are HTML files, easy to edit without code deployment
- Webhook endpoint must be publicly reachable (Render URL needed)
