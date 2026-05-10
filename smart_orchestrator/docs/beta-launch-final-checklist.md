# Beta launch final checklist

1. Set all Render backend env vars:
   - `ENVIRONMENT=prod`
   - `NM_ENVIRONMENT=prod`
   - `AUTH_ENABLED=true`
   - `BETA_INVITE_REQUIRED=true`
   - `BETA_INVITES_TABLE=invites`
   - `APP_BASE_URL=https://beta.neuralmesh.ai`
   - `COOKIE_SECURE=true`
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `STRIPE_MODE=live`
   - `STRIPE_SECRET_KEY`
   - `STRIPE_WEBHOOK_SECRET`
   - `STRIPE_BETA_PRODUCT_ID`
   - `STRIPE_BETA_PRICE_ID`
   - `RESEND_API_KEY`
   - `EMAIL_FROM`
   - `POSTHOG_API_KEY` or leave unset for Redis-only analytics
   - `POSTHOG_HOST`
   - `REDIS_URL`
   - `QDRANT_URL`
   - `ADMIN_SECRET`
   - `ROUTE_MODEL_PREFIX`
   - `CLASSIFY_MODEL`
   - `PRUNE_MODEL`
   - `OTEL_ENABLED`
   - `LOKI_ENABLED`
2. Set Stripe live keys and register `https://api.beta.neuralmesh.ai/webhooks/stripe` with the live signing secret.
3. Set `RESEND_API_KEY` and verify the `EMAIL_FROM` sending domain.
4. Confirm DNS and HTTPS for `beta.`, `api.beta.`, and `install.beta.`.
5. Seed the first 10 root invite codes with `python scripts/seed_beta_invites.py --count 10`.
6. Run `scripts/smoke_e2e_beta.sh` and confirm it passes.
7. Confirm the first real provider node is online and serving jobs.
8. Confirm `/status` returns all green.

