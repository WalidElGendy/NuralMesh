# API key authentication with per-tier Redis sliding-window rate limiting

## Context

The inference endpoint is open to the internet. NeuralMesh needs to authenticate callers,
track usage per key, and enforce tier-based request limits without introducing a full OAuth
server or user registration system in this sprint.

## Decision

Use API keys with an `nm_` prefix and store only SHA-256 hashes in Redis hashes at
`auth:keys:<sha256_hash>`. Runtime requests authenticate with
`Authorization: Bearer <key>`. Admin endpoints use a separate `X-Admin-Secret` header and
can issue, list, and revoke API keys.

Per-key rate limiting uses Redis sorted sets at `ratelimit:<key_hash>` with a 60-second
sliding window. Tier limits are:

- `free`: 10 requests/minute
- `pro`: 60 requests/minute
- `admin`: 9999 requests/minute

`AUTH_ENABLED=false` bypasses Redis auth for local development and CI.

## Consequences

Every inference call is authenticated and rate-limited when auth is enabled. Admins can
issue and revoke keys over REST. The system avoids storing raw API keys and does not depend
on an external auth service.

