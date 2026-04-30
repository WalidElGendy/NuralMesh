# ADR 0006: Stripe Billing and Usage Metering

## Status
Accepted

## Context
Sprint 6 adds Stripe webhook integration for tier promotion/demotion and per-key usage metering.

## Decision
- `app/lib/billing.py`: Stripe webhook signature verification, tier mapping, subscription event handling, usage recording
- `app/routers/webhook.py`: POST /webhook/stripe endpoint (no auth required, raw bytes)
- `app/routers/admin.py`: GET /admin/usage and GET /admin/usage/{key_hash} endpoints
- Redis key patterns: `billing:email:<email>` for emailkey_hash, `usage:<key_hash>` for request/token counts

## Consequences
- Stripe subscriptions automatically promote/demote API key tiers
- Usage is tracked per API key with 30-day TTL
- Tests mock stripe library with unittest.mock
