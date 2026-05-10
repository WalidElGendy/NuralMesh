# ADR 0025 - Beta pricing and trial

**Status:** Accepted  
**Date:** 2026-05-09

## Context
The beta must open to real money while still letting invited users verify product value before subscribing.

## Decision
- Define one paid plan in code: `NeuralMesh Beta`.
- Price is `$19/month`.
- Paid plan includes `5000 requests/day` and priority routing.
- Free trial is `50` requests during the first `7` days from signup.
- Providers do not pay subscriptions; they accept beta participation terms.

## Consequences
+ Pricing is easy to explain and test.
+ Trial gate has a simple, auditable request counter.
+ Provider onboarding stays separate from user billing.
- Daily paid quota enforcement still depends on the existing rate and usage layers.

