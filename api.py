import asyncio
import json
import logging
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import stripe
from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from supabase import create_client


PRODUCTION_ENV = "production"
DEFAULT_ALLOWED_ORIGINS = "https://beta.meshnet.co"
REQUIRED_PRODUCTION_ENV = (
    "DATABASE_URL",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_ANON_KEY",
    "REDIS_URL",
    "QDRANT_URL",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "STRIPE_PRICE_ID_USER_BETA",
    "GROQ_API_KEY",
    "GROQ_MODEL",
    "AUTH_ENABLED",
    "OTEL_ENABLED",
    "LOKI_ENABLED",
    "ALLOWED_ORIGINS",
    "INTERNAL_API_KEY",
    "RESEND_API_KEY",
    "EMAIL_FROM",
    "BETA_INVITE_REQUIRED",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if root.handlers:
        for handler in root.handlers:
            handler.setFormatter(JsonFormatter())
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)


logger = logging.getLogger(__name__)
configure_logging()


def parse_allowed_origins() -> list[str]:
    raw_origins = os.getenv("ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS)
    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


def validate_production_env() -> None:
    if os.getenv("NM_ENV") != PRODUCTION_ENV:
        return

    missing = [name for name in REQUIRED_PRODUCTION_ENV if not os.getenv(name)]
    if missing:
        formatted = ", ".join(missing)
        raise RuntimeError(
            "NeuralMesh beta production startup blocked. Missing required env vars: "
            f"{formatted}. Populate Render/Vercel/Supabase values from config/beta.env.example."
        )


def init_sentry() -> None:
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
    except Exception as error:  # pragma: no cover - dependency is installed in production
        logger.warning("sentry_unavailable: %s", error)
        return

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("NM_ENV", "local"),
        integrations=[
            FastApiIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
    )


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    validate_production_env()
    init_sentry()
    logger.info("api_startup")
    yield


app = FastAPI(title="Distributed AI Inference API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=parse_allowed_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class JobRequest(BaseModel):
    prompt: str = Field(..., min_length=1)


DEMO_API_KEY = "nm_live_sk_3f9a8b2c1d4e5f6a7b8c9d0e1f2a3b4c"


def get_required_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def get_supabase_client():
    supabase_url = get_required_env("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or get_required_env("SUPABASE_KEY")
    return create_client(supabase_url, supabase_key)


@lru_cache
def get_version() -> str:
    for name in ("RENDER_GIT_COMMIT", "GIT_SHA", "COMMIT_SHA"):
        value = os.getenv(name)
        if value:
            return value[:12]

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return "unknown"
    return result.stdout.strip() or "unknown"


def current_env() -> str:
    return os.getenv("NM_ENV", "local")


def get_billing_record(supabase, api_key):
    # Join billing to plans so every authenticated request knows its limits.
    result = (
        supabase.table("billing")
        .select("*, plans(*)")
        .eq("api_key", api_key)
        .limit(1)
        .execute()
    )

    if not result.data:
        return None

    return result.data[0]


def verify_api_key(x_api_key: str = Header(None)):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")

    try:
        supabase = get_supabase_client()
        billing = get_billing_record(supabase, x_api_key)
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Could not verify API key: {error}",
        ) from error

    if not billing:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return {"supabase": supabase, "billing": billing}


def format_billing_response(billing):
    plan = billing["plans"]
    return {
        "plan_name": plan["name"],
        "price_monthly": plan["price_monthly"],
        "request_limit": plan["request_limit"],
        "compute_hours_limit": plan["compute_hours_limit"],
        "api_key": billing["api_key"],
        "requests_today": billing["requests_today"],
        "compute_hours_used": billing["compute_hours_used"],
    }


def increment_requests_today(supabase, billing):
    # Keep the counter update explicit so successful job submissions are metered.
    new_count = billing["requests_today"] + 1
    result = (
        supabase.table("billing")
        .update({"requests_today": new_count})
        .eq("user_id", billing["user_id"])
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=500, detail="Could not update usage counter")


def check_supabase() -> None:
    supabase = get_supabase_client()
    supabase.table("billing").select("user_id").limit(1).execute()


async def check_redis() -> None:
    from redis.asyncio import from_url

    redis_url = get_required_env("REDIS_URL")
    client = from_url(redis_url, decode_responses=True)
    try:
        await client.ping()
    finally:
        await client.aclose()


async def check_qdrant() -> None:
    from qdrant_client import AsyncQdrantClient

    qdrant_url = get_required_env("QDRANT_URL")
    client = AsyncQdrantClient(url=qdrant_url)
    try:
        await client.get_collections()
    finally:
        await client.close()


async def run_ready_check(name: str, check: Any) -> tuple[str, dict[str, str]]:
    try:
        result = check()
        if hasattr(result, "__await__"):
            await result
        return name, {"status": "ok"}
    except Exception as error:
        logger.warning("ready_check_failed name=%s error=%s", name, error)
        return name, {"status": "error", "detail": str(error)}


@app.get("/")
def root_health_check():
    return {"status": "ok"}


@app.get("/health")
def health_check():
    return {"status": "ok", "version": get_version(), "env": current_env()}


@app.get("/readyz")
async def readiness_check(response: Response):
    check_results = await asyncio.gather(
        run_ready_check("supabase", lambda: asyncio.to_thread(check_supabase)),
        run_ready_check("redis", check_redis),
        run_ready_check("qdrant", check_qdrant),
    )
    checks = dict(check_results)
    ready = all(check["status"] == "ok" for check in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if ready else "degraded", "version": get_version(), "env": current_env(), "checks": checks}


@app.post("/submit")
def submit_job(job_request: JobRequest, auth=Depends(verify_api_key)):
    supabase = auth["supabase"]
    billing = auth["billing"]
    plan = billing["plans"]

    if billing["requests_today"] >= plan["request_limit"]:
        raise HTTPException(status_code=429, detail="Request limit reached for current plan")

    try:
        result = (
            supabase.table("jobs")
            .insert(
                {
                    "prompt": job_request.prompt,
                    "status": "pending",
                }
            )
            .execute()
        )
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Could not submit job: {error}",
        ) from error

    if not result.data:
        raise HTTPException(status_code=500, detail="Supabase did not return a job")

    increment_requests_today(supabase, billing)
    return {"id": result.data[0]["id"]}


@app.get("/job/{job_id}")
def get_job(job_id: str, auth=Depends(verify_api_key)):
    # Job reads are also protected so outputs are only visible to valid API keys.
    try:
        result = (
            auth["supabase"]
            .table("jobs")
            .select("status, output")
            .eq("id", job_id)
            .limit(1)
            .execute()
        )
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Could not fetch job: {error}",
        ) from error

    if not result.data:
        raise HTTPException(status_code=404, detail="Job not found")

    job = result.data[0]
    return {
        "status": job.get("status"),
        "output": job.get("output"),
    }


@app.get("/billing/me")
def get_current_billing(auth=Depends(verify_api_key)):
    return format_billing_response(auth["billing"])


@app.post("/billing/upgrade")
def upgrade_billing(auth=Depends(verify_api_key)):
    stripe_secret_key = os.environ.get("STRIPE_SECRET_KEY")
    if not stripe_secret_key:
        return {"checkout_url": "https://checkout.stripe.com/mock"}

    stripe.api_key = stripe_secret_key
    billing = auth["billing"]

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=billing.get("stripe_customer_id") or None,
            client_reference_id=billing["user_id"],
            success_url="http://localhost:8000/dashboard/billing.html?checkout=success",
            cancel_url="http://localhost:8000/dashboard/billing.html?checkout=cancelled",
            line_items=[
                {
                    # Replace this with a real Stripe Price ID before production.
                    "price_data": {
                        "currency": "usd",
                        "product_data": {"name": "NeuralMesh Enterprise"},
                        "unit_amount": 49900,
                        "recurring": {"interval": "month"},
                    },
                    "quantity": 1,
                }
            ],
        )
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Could not create Stripe Checkout Session: {error}",
        ) from error

    return {"checkout_url": session.url}


app.mount("/dashboard", StaticFiles(directory="dashboard", html=True), name="dashboard")
