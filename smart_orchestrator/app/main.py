import asyncio
import json
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from functools import lru_cache
from inspect import isawaitable
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from app.config import ALLOWED_ORIGINS, VERSION
from app.lib.billing import log_stripe_mode_banner
from app.lib.auth import ApiKeyDep
from app.lib.logger import get_logger
from app.lib.metrics import get_metrics
from app.lib.ratelimit import RateLimiter
from app.lib.telemetry import init_telemetry
from app.models.schemas import ApiKeyRecord, ChatRequest
from app.pipeline import run_pipeline
from app.routers.admin import router as admin_router
from app.routers.chat import router as chat_router
from app.routers.beta import router as beta_router
from app.routers.webhook import router as webhook_router
from app.routers.ws import router as ws_router
from app.routers.jobs import router as jobs_router
from app.routers.health import router as health_router
from app.routers.usage import router as usage_router
from app.routers.metrics_router import router as metrics_router
from app.routers.node import router as node_router
from app.routers.provider import router as provider_router
from app.routers.admin_payouts import router as admin_payouts_router
from app.routers.user_dashboard import router as user_dashboard_router
from app.routers.gpu_dashboard import router as gpu_dashboard_router
from app.routers.internal import router as internal_router
from app.routers.pages import router as pages_router
from app.stages.cache import get_qdrant_client, get_redis_client


PRODUCTION_ENV = "production"
REQUIRED_PRODUCTION_ENV = (
    "REDIS_URL",
    "QDRANT_URL",
    "GROQ_API_KEY",
    "GROQ_MODEL",
    "AUTH_ENABLED",
    "ALLOWED_ORIGINS",
)
VALID_SUBSCRIBERS = {"demo-sub", "pro-demo", "enterprise-demo", "sub_demo_pro", "demo-pro"}
logger = get_logger(__name__)


def current_env() -> str:
    return os.getenv("NM_ENV", os.getenv("ENVIRONMENT", "local"))


@lru_cache
def get_version() -> str:
    return os.getenv("GIT_SHA", VERSION)[:12]


def validate_production_env() -> None:
    if current_env() != PRODUCTION_ENV:
        return
    missing = [name for name in REQUIRED_PRODUCTION_ENV if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            "NeuralMesh beta production startup blocked. Missing required env vars: "
            + ", ".join(missing)
        )


@asynccontextmanager
async def lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
    """Initialize telemetry once when the FastAPI app starts."""

    validate_production_env()
    init_telemetry()
    logger.info("orchestrator_startup")
    yield


log_stripe_mode_banner()
app = FastAPI(title="NeuralMesh Smart Orchestrator", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
FastAPIInstrumentor().instrument_app(app)
WEB_DIR = Path(__file__).resolve().parents[1] / "web"
app.mount("/web", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


@app.middleware("http")
async def reject_beta_user_stub_header(request: Request, call_next):
    if request.headers.get("x-beta-user-id") and current_env() in {"prod", "production"}:
        return JSONResponse(
            status_code=400,
            content={"detail": "X-Beta-User-Id is not accepted in production"},
        )
    return await call_next(request)


app.state.environment = current_env()
app.include_router(admin_router, prefix="/admin")
app.include_router(chat_router)
app.include_router(webhook_router, prefix="/webhook")
app.include_router(webhook_router, prefix="/webhooks")
app.include_router(beta_router)
app.include_router(ws_router)
app.include_router(jobs_router, prefix="/jobs")
app.include_router(jobs_router, prefix="/api")
app.include_router(health_router)
app.include_router(usage_router)
app.include_router(metrics_router)
app.include_router(node_router)
app.include_router(provider_router)
app.include_router(admin_payouts_router)
app.include_router(user_dashboard_router)
app.include_router(gpu_dashboard_router)
app.include_router(internal_router)
app.include_router(pages_router)


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


async def _maybe_await(value: object) -> object:
    if isawaitable(value):
        return await value
    return value


async def check_redis() -> None:
    redis_client = await _maybe_await(get_redis_client())
    await redis_client.ping()


async def check_qdrant() -> None:
    qdrant_client = await _maybe_await(get_qdrant_client())
    await qdrant_client.get_collections()


async def run_ready_check(name: str, check: Callable[[], object]) -> tuple[str, dict[str, str]]:
    try:
        result = check()
        await _maybe_await(result)
        return name, {"status": "ok"}
    except Exception as error:
        logger.warning("ready_check_failed name=%s error=%s", name, error)
        return name, {"status": "error", "detail": str(error)}


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
    return {"status": "ok", "version": get_version(), "env": current_env()}


@app.get("/readyz")
async def readiness_check(response: Response) -> dict[str, object]:
    check_results = await asyncio.gather(
        run_ready_check("redis", check_redis),
        run_ready_check("qdrant", check_qdrant),
    )
    checks = dict(check_results)
    ready = all(check["status"] == "ok" for check in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if ready else "degraded",
        "version": get_version(),
        "env": current_env(),
        "checks": checks,
    }


async def enforce_rate_limit(
    response: Response,
    api_key: ApiKeyRecord = Depends(ApiKeyDep),
) -> ApiKeyRecord:
    """Authenticate and rate-limit one protected request."""

    result = await RateLimiter(get_redis_client(), api_key.tier).check_and_increment(
        api_key.hash,
        api_key.tier,
    )
    response.headers["X-RateLimit-Limit"] = str(result.limit)
    response.headers["X-RateLimit-Remaining"] = str(result.remaining)
    response.headers["X-RateLimit-Reset"] = str(result.reset_at)
    return api_key


@app.get("/metrics")
async def metrics(api_key: ApiKeyRecord = Depends(enforce_rate_limit)) -> dict[str, float | int]:
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
async def chat(
    request: ChatRequest,
    response: Response,
    api_key: ApiKeyRecord = Depends(enforce_rate_limit),
) -> StreamingResponse:
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

    stream = StreamingResponse(stream_chat(request), media_type="text/event-stream")
    for header in ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"):
        if header in response.headers:
            stream.headers[header] = response.headers[header]
    return stream
