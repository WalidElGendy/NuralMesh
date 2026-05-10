# ADR 0020: Beta launch architecture

## Status

Accepted for Sprint A.

## Context

The beta launch needs a real production environment before model integration, chat UI, provider installer, and subscriptions are wired in later sprints.

## Decision

NeuralMesh beta uses:

1. Render for the FastAPI backend at `api.beta.meshnet.co`.
2. Vercel for the static beta frontend at `beta.meshnet.co`.
3. A new Supabase project dedicated to beta production data.
4. Redis for rate limiting and cache dependencies.
5. Qdrant for semantic cache readiness.
6. Cloudflare DNS and SSL for `beta.meshnet.co`, `api.beta.meshnet.co`, and `install.beta.meshnet.co`.
7. Sentry for error capture when `SENTRY_DSN` is configured.
8. JSON stdout logs so Render can capture structured application events.

## Topology

Users open `https://beta.meshnet.co` on Vercel. The frontend is static HTML built from `web/` with `scripts/inject-env.js` replacing API and Supabase placeholders during deployment.

API traffic goes to `https://api.beta.meshnet.co` on Render. Render starts `uvicorn api:app --host 0.0.0.0 --port $PORT`. The app refuses to start with `NM_ENV=production` unless all required beta env vars are present.

Supabase stores beta users, providers, provider earnings, billing records, and invites. Redis and Qdrant are checked by `/readyz` so Render can distinguish live app code from a ready production dependency graph.

## Consequences

The environment is production-shaped while intentionally leaving Sprint B model wiring, Sprint C chat UI, Sprint D installer, and Sprint E auth/subscription flows untouched.
