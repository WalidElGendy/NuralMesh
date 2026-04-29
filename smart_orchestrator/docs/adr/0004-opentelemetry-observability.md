# Use OpenTelemetry SDK + Grafana Tempo/Loki for distributed tracing and log aggregation

## Context

We need visibility into cascade routing decisions, cache hit rates per request, and token costs in production without adding per-stage print statements. The Smart Orchestrator now makes multiple dynamic decisions per request, so operators need request-scoped traces and logs that can be correlated.

## Decision

Use the OpenTelemetry SDK with the OTLP gRPC exporter to send traces to Grafana Tempo. Use `python-logging-loki` through the standard Python logging stack to ship structured JSON logs to Grafana Loki. Both are disabled by default with `OTEL_ENABLED=false` and `LOKI_ENABLED=false`, so unit tests and CI run with zero export overhead.

## Consequences

Every HTTP request and every instrumented pipeline stage is traceable. Grafana can show p50/p99 latency per stage, route escalation rates, cache hit rates, and token costs per trace. Logs include `trace_id` and `span_id`, making it possible to jump between route/cache/prune logs and the surrounding request trace.
