# ADR 0021: Llama 3.3 70B Sovereign Nodes and Groq 20% Routing

## Context

The beta needs a sovereign default model on provider GPUs while preserving a
fast fallback path for latency-sensitive or quality-sensitive traffic.

## Decision

Provider nodes default to `llama3.3:70b-instruct-q4_K_M` via `NM_NODE_MODEL`.
Multi-model nodes advertise `NM_NODE_MODELS` in heartbeat payloads.

Inference routing supports three modes:

- `fast`: always route to Groq.
- `sovereign`: always route to a provider node, queueing when none is active.
- `auto`: route deterministically by `hash(user_id + request_id)` using
  `NM_AUTO_ROUTE_GROQ_PERCENT`, defaulting to 20% Groq and 80% sovereign.

Groq uses `GROQ_MODEL`, default `llama-3.3-70b-versatile`, through the Groq
Python SDK streaming API.

## Consequences

- The default model is sovereign and provider-hosted.
- Groq traffic is paid by the platform and logged in `groq_usage`.
- Provider credits accrue only for node-served tokens.
- The Groq percentage can be tuned at runtime without redeploying code.

## Alternatives Considered

- **Sovereign-only beta:** maximizes sovereignty but gives no fast fallback.
- **Groq-only beta:** simplest operations, but it bypasses provider economics.
- **Random per-request split:** easier to implement, but deterministic hashing
  gives stable analysis and predictable user experience.
