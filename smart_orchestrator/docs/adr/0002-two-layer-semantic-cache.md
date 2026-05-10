# ADR 0002: Two-layer semantic cache

## Context

NeuralMesh needs to reduce repeated model work without compromising answer quality. Sprint 2 introduces real cache behavior while the rest of the orchestration pipeline remains mocked. The target is lower token spend through cache hits while preserving safe handling for sensitive prompts and low-confidence classification.

## Decision

We will use two cache layers:

1. Redis hot cache for exact prompt matches with a 300 second TTL.
2. Qdrant semantic cache for near-match retrieval using cosine similarity with a threshold of 0.95.

The 0.95 threshold is intentionally conservative. A lower threshold such as 0.90 could increase hit rate, but it raises the risk of returning an answer for a prompt that is semantically close but materially different.

## Consequences

- Expected cache hit rate improvement is roughly 15% once repeated prompts emerge.
- Expected token spend reduction is roughly 15% because cached answers bypass routing calls.
- Cache lookup adds a small amount of latency, typically 10-30ms when Redis and Qdrant are healthy.
- Redis failures do not break the pipeline; the request falls through to Qdrant.
- Qdrant failures do not break the pipeline; the request proceeds as a cache miss.

## Alternatives considered

- Redis-only: very fast for exact matches but no semantic reuse.
- Qdrant-only: supports semantic reuse but is slower for hot exact repeats.
- Lower Qdrant threshold: improves hit rate but increases false-positive risk.
