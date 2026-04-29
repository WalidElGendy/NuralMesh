import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from app.lib.logger import get_logger
from app.lib.metrics import get_metrics
from app.lib.telemetry import init_telemetry
from app.models.schemas import ChatRequest, ChatResponse, PipelineEvent
from app.pipeline import run_pipeline


VALID_SUBSCRIBERS = {"demo-sub", "pro-demo", "enterprise-demo", "sub_demo_pro", "demo-pro"}
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
    """Initialize telemetry once when the FastAPI app starts."""

    init_telemetry()
    logger.info("orchestrator_startup")
    yield


app = FastAPI(title="NeuralMesh Smart Orchestrator", lifespan=lifespan)
FastAPIInstrumentor().instrument_app(app)


def sse(event: str, payload: dict[str, object]) -> str:
    """Purpose: Serialize one Server-Sent Event frame.

    Args:
        event: SSE event type.
        payload: JSON-safe event payload.

    Returns:
        Encoded SSE frame string.

    Cost/quality target:
        Zero model cost; stable browser-compatible streaming.
    """
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


async def stream_chat(request: ChatRequest) -> AsyncIterator[str]:
    """Purpose: Stream stage, token, and done events for one chat request.

    Args:
        request: Validated chat request.

    Yields:
        SSE frames containing stage progress, token chunks, and final metadata.

    Cost/quality target:
        Zero real provider cost in Sprint 1 while preserving production event shape.
    """
    response = await run_pipeline(request)
    for stage in ("classify", "cache", "prune", "compress", "route", "verify", "settle"):
        yield sse("stage", {"stage": stage, "status": "done"})
    for token in response.answer.split():
        yield sse("token", {"text": f"{token} "})
    yield sse("done", response.model_dump())


@app.get("/health")
async def health() -> dict[str, str]:
    """Purpose: Return service health for local and container checks.

    Args:
        None.

    Returns:
        Health status dictionary.

    Cost/quality target:
        Zero model cost; fast liveness response.
    """
    return {"status": "ok"}


@app.get("/metrics")
async def metrics() -> dict[str, float | int]:
    """Purpose: Return Sprint 3 in-memory cache, classify, route, and prune metrics.

    Args:
        None.

    Returns:
        Cache hit rate, classify counters, route counters, prune counters, and
        estimated USD savings.

    Cost/quality target:
        Zero external dependency metrics endpoint for Sprint 3; Prometheus is deferred.
    """

    return await get_metrics()


@app.post("/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    """Purpose: Accept chat requests and stream Smart Orchestrator output.

    Args:
        request: Subscriber, messages, system prompt, and stream flag.

    Returns:
        Server-Sent Events response with stage/token/done events.

    Cost/quality target:
        Mocked end-to-end path that validates pipeline cost and quality controls.
    """
    if request.subscriber_id not in VALID_SUBSCRIBERS:
        raise HTTPException(status_code=401, detail="Unknown subscriber_id")

    return StreamingResponse(stream_chat(request), media_type="text/event-stream")
