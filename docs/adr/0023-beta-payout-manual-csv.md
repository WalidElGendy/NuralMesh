# ADR 0023: Beta payout manual CSV

## Status

Accepted

## Context

Sprint D needs provider earnings visibility and beta payouts, but live Stripe Connect onboarding and transfers are explicitly deferred to a later sprint. The beta still needs a repeatable month-end process.

## Decision

Provider earnings accrue as credits: 1 credit per 1000 tokens served. The beta USD value per credit is a configurable constant, `BETA_CREDIT_USD`, defaulting to `0.0025`.

At month end, an operator runs:

`python scripts/export_payouts.py --period YYYY-MM`

The script reads successful `provider_jobs`, sums credits by provider, joins provider email and payout method, and writes:

`provider_id,email,payout_method,credits,USD equivalent,period`

The provider dashboard states: "Beta payouts are processed manually within 7 days of month-end. Stripe Connect coming post-beta."

## Consequences

- No live Stripe user flow is introduced in Sprint D.
- Finance can pay via PayPal, wire, or crypto from the CSV during beta.
- The dashboard and CSV use the same credit-rate constant, so operators can adjust beta economics without code-path changes.
- Stripe Connect can replace this export later without changing the provider claim flow.
