# ADR 0003: Confidence-Gated Cascade Routing

## Context

Always sending every prompt to the strongest frontier model is simple, but it
destroys the NeuralMesh cost advantage. Many prompts can be answered by local
or cheaper models, while harder prompts still need escalation.

## Decision

Sprint 3 uses domain-specific model ladders with a confidence gate. The router
starts with the cheapest model in the domain ladder, asks the model to append a
`Confidence: X.XX` line, and accepts the answer when confidence is at least
`0.72`.

The `0.72` threshold is intentionally lower than `0.80`: high enough to catch
weak answers, but low enough to avoid over-escalating simple prompts to
frontier models.

Confidence extraction is done with a response text heuristic instead of a
separate confidence model. This avoids an extra model call, keeps latency low,
and keeps average route-call token cost below the Sprint 3 target.

Sensitive queries bypass local models and route directly to `claude-sonnet`.

## Consequences

- Simple prompts should stay on local/cheap models, reducing token cost.
- About 5% of queries are expected to escalate to frontier models as the
  classifier and confidence prompt mature.
- Responses depend on models following the confidence-line instruction; when
  absent, the router defaults to `0.75`.

## Alternatives Considered

- **Always frontier:** highest quality baseline, but too expensive.
- **Cost-based routing only:** promising, but requires richer per-model cost and
  quality telemetry; deferred to Sprint 5+.
- **Separate confidence model:** more robust scoring, but adds latency and cost.
