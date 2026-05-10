from __future__ import annotations

import os

from opentelemetry import trace
import opentelemetry.trace as trace_api
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.trace import NoOpTracerProvider

from app.config import VERSION

SERVICE_NAME = "neuralmesh-orchestrator"
_INITIALIZED = False


def init_telemetry(force: bool = False) -> None:
    """Initialize OpenTelemetry tracing.

    Args:
        None.

    Returns:
        None.

    Cost/quality target:
        Noop provider by default for zero CI/test overhead; OTLP gRPC export only
        when explicitly enabled.
    """

    global _INITIALIZED
    if _INITIALIZED and not force:
        return

    def set_provider(provider: object) -> None:
        if force:
            trace_api._TRACER_PROVIDER = None  # type: ignore[attr-defined]
            trace_api._TRACER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]
        trace.set_tracer_provider(provider)  # type: ignore[arg-type]

    if os.getenv("OTEL_ENABLED", "false").lower() != "true":
        set_provider(NoOpTracerProvider())
        _INITIALIZED = True
        return

    resource = Resource.create(
        {
            "service.name": SERVICE_NAME,
            "service.version": VERSION,
        }
    )
    provider = TracerProvider(resource=resource)
    if not force:
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
                )
            )
        )
    set_provider(provider)
    _INITIALIZED = True


tracer = trace.get_tracer("neuralmesh.orchestrator")
