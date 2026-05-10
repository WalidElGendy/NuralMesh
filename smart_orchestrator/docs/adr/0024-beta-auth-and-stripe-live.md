# ADR 0024 - Beta auth and Stripe live wiring

**Status:** Accepted  
**Date:** 2026-05-09

## Context
Beta launch needs real signup, login, billing, invites, and provider onboarding. The prior beta user header was a stub and is not safe for production.

## Decision
- Use one Supabase Auth pool for AI users and providers.
- Providers are normal Supabase Auth users with a row in `providers`.
- Store the Supabase access token in an HttpOnly cookie and use a readable CSRF cookie for state-changing beta endpoints.
- Reject `X-Beta-User-Id` in production.
- Use Stripe live Checkout, Customer Portal, and signed webhooks for the `NeuralMesh Beta` plan.
- Keep existing API-key endpoints for legacy clients while adding beta session endpoints under `/api`.

## Consequences
+ Signup and login are production-ready with Supabase confirmation links.
+ Billing state is updated only from signed Stripe webhooks.
+ Static web pages can use sessions without storing access tokens in local storage.
- Supabase table names and Stripe live IDs must be configured before launch.

