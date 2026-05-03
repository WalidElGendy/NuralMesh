# ADR 0008  Stripe Live Mode and Webhook Security

**Status:** Accepted  
**Date:** 2025-05-03

## Context
We need to accept real USD payments without hardcoding keys or accidentally running live mode in tests.

## Decision
- All Stripe credentials come from env vars: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`
- `STRIPE_MODE=mock|test|live` env var controls which mode the app thinks it is in
- On startup, `log_stripe_mode_banner()` logs a clearly visible banner so `LIVE` mode is unmistakable
- Tests set `STRIPE_MODE=mock` and mock `stripe.checkout.Session.create`
- Webhook signature is always verified via `stripe.Webhook.construct_event` with the secret

## Consequences
+ Impossible to accidentally push live keys to test
+ Clear audit trail in startup logs for which mode is active
+ CI never makes real Stripe calls
- Requires manual key rotation in Render for live deployment
