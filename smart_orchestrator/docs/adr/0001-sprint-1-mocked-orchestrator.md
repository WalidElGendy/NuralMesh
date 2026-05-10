# ADR 0001: Sprint 1 mocked orchestrator

## Status

Accepted

## Context

Sprint 1 needs a working Smart Orchestrator before real provider gRPC stubs, real
mesh-hosted models, Qdrant collections, Redis streams, and PostgreSQL migrations
are available.

## Decision

The orchestrator uses async interfaces and production-shaped schemas while
mocking external systems in memory. Provider dispatch returns proof-of-compute,
latency, confidence, and self-critique fields. LiteLLM frontier calls are used
only when matching API keys are configured; otherwise they fall back to mocks.

## Consequences

The module can run end-to-end with zero credentials. Future sprints can replace
the mock internals without changing the pipeline contract.
