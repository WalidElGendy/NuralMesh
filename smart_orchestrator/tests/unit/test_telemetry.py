import json
import logging

from opentelemetry import trace
from opentelemetry.trace import NoOpTracerProvider

from app.lib import logger as logger_module
from app.lib import telemetry


def reset_logging() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)


def test_noop_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_ENABLED", "false")
    telemetry.init_telemetry(force=True)
    assert isinstance(trace.get_tracer_provider(), NoOpTracerProvider)


def test_span_created(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_ENABLED", "true")
    telemetry.init_telemetry(force=True)
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("unit") as span:
        assert span.get_span_context().trace_id != 0


def test_logger_no_loki(monkeypatch) -> None:
    reset_logging()
    monkeypatch.setenv("LOKI_ENABLED", "false")
    log = logger_module.get_logger("unit.no_loki")
    handlers = logging.getLogger().handlers
    assert handlers
    assert not any(handler.__class__.__name__ == "LokiHandler" for handler in handlers)
    log.info("hello")


def test_logger_injects_trace_id(monkeypatch, capsys) -> None:
    reset_logging()
    monkeypatch.setenv("LOKI_ENABLED", "false")
    monkeypatch.setenv("OTEL_ENABLED", "true")
    telemetry.init_telemetry(force=True)
    log = logger_module.get_logger("unit.trace")
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("log-span"):
        log.info("inside span", extra={"component": "test"})
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip().splitlines()[-1])
    assert payload["trace_id"] != "0" * 32
    assert payload["span_id"] != "0" * 16
    assert payload["component"] == "test"
