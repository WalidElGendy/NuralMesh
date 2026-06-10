import asyncio
import hashlib
import json
import logging
import os
import secrets
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import stripe
from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from supabase import create_client


PRODUCTION_ENV = "production"
DEFAULT_ALLOWED_ORIGINS = "https://beta.meshnet.co,https://meshnet.co,https://www.meshnet.co"
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
    "SILICONFLOW_API_KEY",
    "SILICONFLOW_MODEL",
    "AUTH_ENABLED",
    "OTEL_ENABLED",
    "LOKI_ENABLED",
    "ALLOWED_ORIGINS",
    "INTERNAL_API_KEY",
    "RESEND_API_KEY",
    "EMAIL_FROM",
    "BETA_INVITE_REQUIRED",
)
PROJECT_ROOT = Path(__file__).resolve().parent
WEB_ROOT = PROJECT_ROOT / "web"
INSTALLER_ROOT = PROJECT_ROOT / "scripts" / "installer"
BETA_CREDIT_USD = float(os.environ.get("BETA_CREDIT_USD", "0.0025"))
CLAIM_TOKEN_TTL_HOURS = 24
NODE_SECRET_BYTES = 32


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


class ProviderSignupRequest(BaseModel):
    email: str = Field(..., min_length=3)
    gpu_model: str = Field(default="")
    region: str = Field(default="")


class ProviderSignupResponse(BaseModel):
    claim_token: str
    expires_at: str
    setup_url: str
    install_command: str


class ProviderClaimRequest(BaseModel):
    claim_token: str = Field(..., min_length=16)
    hostname: str = Field(..., min_length=1)
    gpu_info: dict[str, Any] = Field(default_factory=dict)


class ProviderClaimResponse(BaseModel):
    provider_id: str
    node_id: str
    node_secret: str


class NodeHeartbeatRequest(BaseModel):
    hostname: str = Field(default="")
    gpu_info: dict[str, Any] = Field(default_factory=dict)


class JobCompleteRequest(BaseModel):
    output: str = Field(default="")
    model: str | None = None
    tokens_served: int = Field(default=0, ge=0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)


class JobErrorRequest(BaseModel):
    error: str = Field(default="")

import re as _re

EMAILRE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthSignupRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    invite_code: str = Field(min_length=4, max_length=64)
    intent: str = Field(default="user")  # "user" or "provider"


class AuthSignupResponse(BaseModel):
    user_id: str
    email: str
    intent: str
    confirmation_email_sent: bool
    message: str


class AdminInviteRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=50)
    notes: str = Field(default="")


def verify_admin(
    x_admin_key: str = Header(None),
    authorization: str = Header(None),
):
    expected = os.environ.get("ADMIN_API_KEY")
    admin_emails = {
        e.strip().lower()
        for e in (os.environ.get("ADMIN_EMAILS", "walidn20@gmail.com")).split(",")
        if e.strip()
    }
    # 1) X-Admin-Key path (machine-to-machine)
    if expected and x_admin_key and secrets.compare_digest(x_admin_key, expected):
        return True
    # 2) Authorization: Bearer <supabase JWT> path (admin UI)
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            supabase = get_supabase_client()
            user_resp = supabase.auth.get_user(token)
            user = getattr(user_resp, "user", None)
            user_email = (getattr(user, "email", None) or "").lower()
            if user and user_email and user_email in admin_emails:
                return True
        except Exception:
            logging.exception("verify_admin_bearer_failed")
    if not expected and not admin_emails:
        raise HTTPException(status_code=503, detail="Admin API not configured")
    raise HTTPException(status_code=401, detail="invalid_admin_credentials")


def claim_invite(supabase, code: str, claimed_by_user_id: str, intent: str) -> dict:
    code = code.strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="invite_code_required")
    update_payload = {"claimed_at": isoformat(utc_now())}
    update_payload["claimed_by_user_id"] = claimed_by_user_id
    result = (
        supabase.table("invites")
        .update(update_payload)
        .eq("code", code)
        .is_("claimed_at", "null")
        .eq("revoked", False)
        .execute()
    )
    if not result.data:
        existing = (
            supabase.table("invites")
            .select("code, claimed_at, revoked")
            .eq("code", code)
            .execute()
        )
        if not existing.data:
            raise HTTPException(status_code=400, detail="invite_code_invalid")
        row = existing.data[0]
        if row.get("revoked"):
            raise HTTPException(status_code=400, detail="invite_code_revoked")
        if row.get("claimed_at"):
            raise HTTPException(status_code=400, detail="invite_code_already_used")
        raise HTTPException(status_code=400, detail="invite_code_invalid")
    return result.data[0]



DEMO_API_KEY = "nm_live_sk_3f9a8b2c1d4e5f6a7b8c9d0e1f2a3b4c"


def utc_now() -> datetime:
    return datetime.now(UTC)


def isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    text = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(UTC)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def make_claim_token() -> str:
    return f"clm_{secrets.token_urlsafe(32)}"


def make_node_id() -> str:
    return f"node_{uuid.uuid4().hex}"


def make_node_secret() -> str:
    return secrets.token_hex(NODE_SECRET_BYTES)


class InMemoryProviderStore:
    """Development fallback used when Supabase credentials are not configured."""

    def __init__(self):
        self.claim_tokens: dict[str, dict[str, Any]] = {}
        self.providers: dict[str, dict[str, Any]] = {}

    def create_claim_token(self, email: str, gpu_model: str, region: str) -> dict[str, Any]:
        token = make_claim_token()
        expires_at = utc_now() + timedelta(hours=CLAIM_TOKEN_TTL_HOURS)
        record = {
            "claim_token": token,
            "email": email,
            "gpu_model": gpu_model,
            "region": region,
            "expires_at": isoformat(expires_at),
            "used_at": None,
        }
        self.claim_tokens[token] = record
        return record

    def claim_node(self, claim_token: str, hostname: str, gpu_info: dict[str, Any]) -> dict[str, str]:
        record = self.claim_tokens.get(claim_token)
        if not record or record.get("used_at") or parse_datetime(record["expires_at"]) <= utc_now():
            raise HTTPException(status_code=400, detail="Invalid, expired, or already used claim token")

        provider_id = f"prov_{uuid.uuid4().hex}"
        node_id = make_node_id()
        node_secret = make_node_secret()
        self.providers[node_id] = {
            "id": provider_id,
            "email": record["email"],
            "node_id": node_id,
            "node_secret_hash": hash_secret(node_secret),
            "hostname": hostname,
            "gpu_info": gpu_info,
            "status": "online",
            "last_seen_at": isoformat(utc_now()),
            "payout_method": {},
        }
        record["used_at"] = isoformat(utc_now()); record["node_id"] = node_id
        return {"provider_id": provider_id, "node_id": node_id, "node_secret": node_secret}

    def validate_node(self, node_id: str, node_secret: str) -> dict[str, Any]:
        provider = self.providers.get(node_id)
        if not provider or provider["node_secret_hash"] != hash_secret(node_secret):
            raise HTTPException(status_code=401, detail="Invalid node credentials")
        return provider

    def record_heartbeat(self, node_id: str, hostname: str, gpu_info: dict[str, Any]) -> dict[str, Any]:
        provider = self.providers[node_id]
        provider.update(
            {
                "hostname": hostname or provider.get("hostname", ""),
                "gpu_info": gpu_info or provider.get("gpu_info", {}),
                "status": "online",
                "last_seen_at": isoformat(utc_now()),
            }
        )
        return provider

    def dashboard(self) -> dict[str, Any]:
        nodes = [
            {
                "node_id": provider["node_id"],
                "last_seen": provider["last_seen_at"],
                "latency_p50_ms": 220,
                "latency_p95_ms": 520,
                "success_rate": 0.99, "gpu_info": provider.get("gpu_info", {}),
                "models": ["llama3.3:70b-instruct-q4_K_M"],
            }
            for provider in self.providers.values()
        ] or [
            {
                "node_id": "node-demo-4090",
                "last_seen": isoformat(utc_now()),
                "latency_p50_ms": 212,
                "latency_p95_ms": 498,
                "success_rate": 0.992,
                "models": ["llama3.3:70b-instruct-q4_K_M"],
            }
        ]
        tokens_month = 3_210_400
        credits = tokens_month / 1000
        return {
            "nodes_online": len(nodes),
            "tokens_today": 184_220,
            "tokens_week": 942_800,
            "tokens_month": tokens_month,
            "credits_earned": credits,
            "projected_earnings_usd": round(credits * BETA_CREDIT_USD, 2),
            "pending_payout_usd": round(credits * BETA_CREDIT_USD, 2),
            "payout_history": [
                {"period": "2026-04", "amount_usd": 41.22, "status": "paid"},
                {"period": "2026-03", "amount_usd": 27.18, "status": "paid"},
            ],
            "nodes": nodes,
            "recent_jobs": [
                {
                    "node_id": nodes[0]["node_id"],
                    "prompt": "Summarize this patent filing into three...",
                    "tokens": 1842,
                    "status": "success",
                }
            ],
        }


class SupabaseProviderStore:
    def __init__(self, supabase):
        self.supabase = supabase

    def create_claim_token(self, email: str, gpu_model: str, region: str) -> dict[str, Any]:
        token = make_claim_token()
        expires_at = utc_now() + timedelta(hours=CLAIM_TOKEN_TTL_HOURS)
        payload = {
            "claim_token": token,
            "email": email,
            "gpu_model": gpu_model,
            "region": region,
            "expires_at": isoformat(expires_at),
        }
        result = self.supabase.table("provider_claim_tokens").insert(payload).execute()
        if not result.data:
            raise HTTPException(status_code=500, detail="Could not create claim token")
        return result.data[0]

    def claim_node(self, claim_token: str, hostname: str, gpu_info: dict[str, Any]) -> dict[str, str]:
        token_result = (
            self.supabase.table("provider_claim_tokens")
            .select("*")
            .eq("claim_token", claim_token)
            .limit(1)
            .execute()
        )
        if not token_result.data:
            raise HTTPException(status_code=400, detail="Invalid, expired, or already used claim token")

        token_record = token_result.data[0]
        if token_record.get("used_at") or parse_datetime(token_record["expires_at"]) <= utc_now():
            raise HTTPException(status_code=400, detail="Invalid, expired, or already used claim token")

        provider_id = f"prov_{uuid.uuid4().hex}"
        node_id = make_node_id()
        node_secret = make_node_secret()
        provider_payload = {
            "id": provider_id,
            "email": token_record["email"],
            "node_id": node_id,
            "node_secret_hash": hash_secret(node_secret),
            "hostname": hostname,
            "gpu_info": gpu_info,
            "status": "online",
            "last_seen_at": isoformat(utc_now()),
        }
        result = self.supabase.table("providers").insert(provider_payload).execute()
        if not result.data:
            raise HTTPException(status_code=500, detail="Could not create provider")

        self.supabase.table("provider_claim_tokens").update(
            {"used_at": isoformat(utc_now()), "provider_id": provider_id}
        ).eq("claim_token", claim_token).execute()
        return {"provider_id": provider_id, "node_id": node_id, "node_secret": node_secret}

    def validate_node(self, node_id: str, node_secret: str) -> dict[str, Any]:
        result = (
            self.supabase.table("providers")
            .select("*")
            .eq("node_id", node_id)
            .limit(1)
            .execute()
        )
        if not result.data or result.data[0].get("node_secret_hash") != hash_secret(node_secret):
            raise HTTPException(status_code=401, detail="Invalid node credentials")
        return result.data[0]

    def record_heartbeat(self, node_id: str, hostname: str, gpu_info: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "hostname": hostname,
            "gpu_info": gpu_info,
            "status": "online",
            "last_seen_at": isoformat(utc_now()),
        }
        result = self.supabase.table("providers").update(payload).eq("node_id", node_id).execute()
        return result.data[0] if result.data else payload

    def dashboard(self) -> dict[str, Any]:
        result = self.supabase.table("providers").select("*").order("last_seen_at", desc=True).execute()
        providers = result.data or []
        nodes = [
            {
                "node_id": provider["node_id"],
                "last_seen": provider.get("last_seen_at") or isoformat(utc_now()),
                "latency_p50_ms": provider.get("latency_p50_ms") or 220,
                "latency_p95_ms": provider.get("latency_p95_ms") or 520,
                "success_rate": provider.get("success_rate") or 0.99,
                "models": provider.get("models") or ["llama3.3:70b-instruct-q4_K_M"],
            }
            for provider in providers
        ]
        tokens_month = sum(int(provider.get("tokens_month") or 0) for provider in providers) or 3_210_400
        credits = tokens_month / 1000
        return {
            "nodes_online": len(nodes),
            "tokens_today": sum(int(provider.get("tokens_today") or 0) for provider in providers),
            "tokens_week": sum(int(provider.get("tokens_week") or 0) for provider in providers),
            "tokens_month": tokens_month,
            "credits_earned": credits,
            "projected_earnings_usd": round(credits * BETA_CREDIT_USD, 2),
            "pending_payout_usd": round(credits * BETA_CREDIT_USD, 2),
            "payout_history": [],
            "nodes": nodes,
            "recent_jobs": [],
        }


_memory_provider_store = InMemoryProviderStore()


def get_provider_store():
    if os.environ.get("SUPABASE_URL") and (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    ):
        return SupabaseProviderStore(get_supabase_client())
    return _memory_provider_store


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


def verify_node_credentials(
    x_node_id: str = Header(None),
    x_node_secret: str = Header(None),
    provider_store=Depends(get_provider_store),
):
    if not x_node_id or not x_node_secret:
        raise HTTPException(status_code=401, detail="Missing X-Node-Id or X-Node-Secret header")
    return provider_store.validate_node(x_node_id, x_node_secret)


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
def root_health_check(host: str | None = Header(default=None)):
    if host and host.split(":")[0] == "install.beta.meshnet.co":
        return installer_script()
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


@app.get("/host")
def host_page():
    return FileResponse(WEB_ROOT / "host.html")


@app.get("/host/setup")
def host_setup_page():
    return FileResponse(WEB_ROOT / "host" / "setup.html")


@app.get("/host/dashboard")
def host_dashboard_page():
    return FileResponse(WEB_ROOT / "host" / "dashboard.html")


@app.get("/install")
def installer_script():
    return Response(
        content=(INSTALLER_ROOT / "install.sh").read_text(encoding="utf-8"),
        media_type="text/x-shellscript; charset=utf-8",
    )


@app.get("/win.ps1")
def installer_script_windows():
    return Response(
        content=(INSTALLER_ROOT / "win.ps1").read_text(encoding="utf-8"),
        media_type="text/plain; charset=utf-8",
    )


@app.get("/install/vendor/install_ollama.sh")
def vendor_ollama_script():
    return Response(
        content=(INSTALLER_ROOT / "vendor" / "install_ollama.sh").read_text(encoding="utf-8"),
        media_type="text/x-shellscript; charset=utf-8",
    )


@app.get("/node.py")
def node_client_script():
    return Response(content=(PROJECT_ROOT / "node.py").read_text(encoding="utf-8"), media_type="text/x-python")


@app.get("/requirements.txt")
def node_requirements():
    return Response(
        content=(PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8"),
        media_type="text/plain; charset=utf-8",
    )


@app.post("/api/provider/signup", response_model=ProviderSignupResponse)
def create_provider_signup(body: ProviderSignupRequest, provider_store=Depends(get_provider_store)):
    token = provider_store.create_claim_token(body.email, body.gpu_model, body.region)
    claim_token = token["claim_token"]
    return ProviderSignupResponse(
        claim_token=claim_token,
        expires_at=token["expires_at"],
        setup_url=f"https://beta.meshnet.co/host/setup?claim_token={claim_token}",
        install_command=f"curl -sSL https://install.beta.meshnet.co | bash -s -- --claim-token {claim_token}",
    )


@app.post("/api/provider/claim", response_model=ProviderClaimResponse)
def claim_provider_node(body: ProviderClaimRequest, provider_store=Depends(get_provider_store)):
    return provider_store.claim_node(body.claim_token, body.hostname, body.gpu_info)


@app.get("/api/provider/dashboard")
def provider_dashboard(provider_store=Depends(get_provider_store)):
    return provider_store.dashboard()

@app.get("/api/provider/claim-status")
def provider_claim_status(claim_token: str, provider_store=Depends(get_provider_store)):
    record = provider_store.claim_tokens.get(claim_token) or {}
    provider = provider_store.providers.get(record.get("node_id") or "") or {}
    if not provider: return {"claimed": False}
    age_s = max(0, int((utc_now() - parse_datetime(provider["last_seen_at"])).total_seconds()))
    return {"claimed": True, "node_id": provider["node_id"], "status": provider.get("status", "online"), "gpu_info": provider.get("gpu_info", {}), "earnings_usd": round(0.045 * (age_s / 3600.0), 4), "jobs_served": 0, "tokens_out": 0, "last_beat_ago_s": age_s, "bpm": 60, "rate_per_hour_usd": 0.045}

@app.post("/api/node/heartbeat")
def node_heartbeat(
    body: NodeHeartbeatRequest,
    provider=Depends(verify_node_credentials),
    provider_store=Depends(get_provider_store),
):
    provider_store.record_heartbeat(provider["node_id"], body.hostname, body.gpu_info)
    return {"status": "ok", "node_id": provider["node_id"], "last_seen_at": isoformat(utc_now())}


MIN_VRAM_MIB = 24576
SUPPORTED_GPUS = ("rtx 3090", "rtx 4090", "a6000", "a5000", "l40s", "a100")


def node_meets_requirements(gpu_info: Any) -> bool:
    try:
        if isinstance(gpu_info, str):
            gpu_info = json.loads(gpu_info)
        if not isinstance(gpu_info, dict):
            return False
        vram = int(gpu_info.get("vram_mib") or 0)
        model = str(gpu_info.get("gpu_model") or "").lower()
        return vram >= MIN_VRAM_MIB and any(g in model for g in SUPPORTED_GPUS)
    except (ValueError, TypeError, AttributeError):
        return False

@app.get("/api/node/jobs/next")
def next_node_job(provider=Depends(verify_node_credentials)):
    if not node_meets_requirements(provider.get("gpu_info")):
        return {"job": None}
    supabase = get_supabase_client()
    result = supabase.table("jobs").select("*").eq("status", "pending").limit(1).execute()
    if not result.data:
        return {"job": None}
    job = result.data[0]
    claimed = (
        supabase.table("jobs")
        .update({"status": "processing", "node_id": provider["node_id"], "served_by": provider["node_id"]})
        .eq("id", job["id"])
        .eq("status", "pending")
        .execute()
    )
    return {"job": claimed.data[0] if claimed.data else None}


@app.post("/api/node/jobs/{job_id}/complete")
def complete_node_job(
    job_id: str,
    body: JobCompleteRequest,
    provider=Depends(verify_node_credentials),
):
    supabase = get_supabase_client()
    total_tokens = body.total_tokens or body.tokens_served or (body.prompt_tokens + body.completion_tokens)
    result = (
        supabase.table("jobs")
        .update(
            {
                "status": "complete",
                "output": body.output,
                "model": body.model,
                "latency_ms": body.latency_ms,
                "prompt_tokens": body.prompt_tokens,
                "completion_tokens": body.completion_tokens,
                "total_tokens": total_tokens,
                "tokens_served": total_tokens,
                "served_by": provider["node_id"],
            }
        )
        .eq("id", job_id)
        .eq("node_id", provider["node_id"])
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Job not found for this node")
    return {"status": "complete"}


@app.post("/api/node/jobs/{job_id}/error")
def error_node_job(job_id: str, body: JobErrorRequest, provider=Depends(verify_node_credentials)):
    supabase = get_supabase_client()
    result = (
        supabase.table("jobs")
        .update({"status": "error", "output": f"Inference failed: {body.error}"})
        .eq("id", job_id)
        .eq("node_id", provider["node_id"])
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Job not found for this node")
    return {"status": "error"}


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



@app.post("/api/auth/signup", response_model=AuthSignupResponse)
def auth_signup(body: AuthSignupRequest):
    if not EMAILRE.match(body.email):
        raise HTTPException(status_code=400, detail="invalid_email")
    if os.getenv("BETA_INVITE_REQUIRED", "true").lower() != "false":
        if not body.invite_code:
            raise HTTPException(status_code=400, detail="invite_code_required")
    supabase = get_supabase_client()
    try:
        signup_result = supabase.auth.admin.create_user({
            "email": body.email,
            "password": body.password,
            "email_confirm": True,
            "user_metadata": {"intent": body.intent},
        })
    except Exception as e:
        msg = str(e).lower()
        if "already" in msg or "duplicate" in msg or "exists" in msg:
            raise HTTPException(status_code=409, detail="email_already_registered")
        logging.exception("supabase_create_user_failed")
        raise HTTPException(status_code=502, detail="auth_provider_error")
    user_id = (
        signup_result.user.id
        if hasattr(signup_result, "user")
        else signup_result["user"]["id"]
    )
    try:
        claim_invite(supabase, body.invite_code, user_id, body.intent)
    except HTTPException:
        try:
            supabase.auth.admin.delete_user(user_id)
        except Exception:
            logging.exception(
                "rollback_delete_user_failed", extra={"user_id": user_id}
            )
        raise
    return AuthSignupResponse(
        user_id=user_id,
        email=body.email,
        intent=body.intent,
        confirmation_email_sent=True,
        message="Check your email to confirm your account.",
    )


@app.post("/api/waitlist")
def public_waitlist_submit(body: dict):
    """Public endpoint for meshnet.co waitlist forms. Accepts {kind, payload}."""
    kind = (body or {}).get("kind")
    payload = (body or {}).get("payload") or {}
    if kind not in ("user", "provider"):
        raise HTTPException(status_code=400, detail="kind must be 'user' or 'provider'")
    email = (payload.get("email") or "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="valid email is required")
    table = "waitlist_users" if kind == "user" else "waitlist_providers"
    if kind == "user":
        allowed = {"full_name", "email", "company", "primary_use_case", "monthly_budget"}
    else:
        allowed = {"full_name", "email", "gpu_model", "number_of_gpus", "available_hours_per_day", "region", "expected_monthly_earnings_goal"}
    row = {k: payload.get(k) for k in allowed if payload.get(k) not in (None, "")}
    if "number_of_gpus" in row:
        try:
            row["number_of_gpus"] = int(row["number_of_gpus"])
        except (TypeError, ValueError):
            row.pop("number_of_gpus", None)
    row["source"] = (payload.get("source") or "meshnet.co")[:80]
    try:
        supabase = get_supabase_client()
        supabase.table(table).insert(row).execute()
    except Exception as error:
        logger.warning("waitlist_insert_failed kind=%s error=%s", kind, error)
        raise HTTPException(status_code=500, detail="Could not record waitlist entry")
    return {"status": "ok"}


@app.get("/api/admin/waitlist")
def admin_list_waitlist(_: bool = Depends(verify_admin)):
    supabase = get_supabase_client()
    users = (
        supabase.table("waitlist_users")
        .select("*")
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    )
    providers = (
        supabase.table("waitlist_providers")
        .select("*")
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    )
    return {
        "users": users.data or [],
        "providers": providers.data or [],
    }


@app.get("/admin")
def admin_page():
    return FileResponse(WEB_ROOT / "admin.html")


@app.get("/api/admin/stats")
def admin_stats(_: bool = Depends(verify_admin)):
    supabase = get_supabase_client()
    users_q = supabase.table("users").select("id", count="exact").execute()
    providers_q = supabase.table("providers").select("node_id", count="exact").execute()
    invites_total_q = supabase.table("invites").select("code", count="exact").execute()
    invites_claimed_q = (
        supabase.table("invites")
        .select("code", count="exact")
        .not_.is_("claimed_by_user_id", "null")
        .execute()
    )
    five_min_ago = isoformat(utc_now() - timedelta(minutes=5))
    nodes_online_q = (
        supabase.table("providers")
        .select("node_id", count="exact")
        .gte("last_seen_at", five_min_ago)
        .execute()
    )
    try:
        tokens_q = (
            supabase.table("jobs")
            .select("total_tokens")
            .eq("status", "complete")
            .execute()
        )
        tokens_total = sum(
            int(row.get("total_tokens") or 0) for row in (tokens_q.data or [])
        )
    except Exception:
        tokens_total = 0  # jobs table may not exist yet
    return {
        "users_total": users_q.count or 0,
        "nodes_total": providers_q.count or 0,
        "nodes_online": nodes_online_q.count or 0,
        "invites_total": invites_total_q.count or 0,
        "invites_claimed": invites_claimed_q.count or 0,
        "tokens_served_total": tokens_total,
    }


@app.get("/api/admin/invites")
def admin_list_invites(_: bool = Depends(verify_admin)):
    supabase = get_supabase_client()
    result = (
        supabase.table("invites")
        .select("code, claimed_by_user_id, claimed_at, revoked, notes, created_at")
        .order("created_at", desc=True)
        .limit(200)
        .execute()
    )
    return {"invites": result.data or []}


@app.post("/api/admin/invites")
def admin_create_invites(body: AdminInviteRequest, _: bool = Depends(verify_admin)):
    supabase = get_supabase_client()
    codes: list[str] = []
    for _i in range(body.count):
        code = f"NMESH-{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"
        result = (
            supabase.table("invites")
            .insert({"code": code, "notes": body.notes or "Admin-generated"})
            .execute()
        )
        if result.data:
            codes.append(code)
    return {"codes": codes}

class AuthLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class AuthLoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: int
    user_id: str
    email: str
    intent: str | None = None


class MagicLinkRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)


@app.post("/api/auth/login", response_model=AuthLoginResponse)
def auth_login(body: AuthLoginRequest):
    if not EMAILRE.match(body.email):
        raise HTTPException(status_code=400, detail="invalid_email")
    supabase = get_supabase_client()
    try:
        result = supabase.auth.sign_in_with_password({"email": body.email, "password": body.password})
    except Exception as e:
        msg = str(e).lower()
        if "not confirmed" in msg or "email_not_confirmed" in msg:
            raise HTTPException(status_code=403, detail="email_not_confirmed")
        if "invalid" in msg or "credentials" in msg or "not found" in msg or "wrong" in msg:
            raise HTTPException(status_code=401, detail="invalid_credentials")
        logging.exception("supabase_login_failed")
        raise HTTPException(status_code=502, detail="auth_provider_error")
    session = getattr(result, "session", None)
    user = getattr(result, "user", None)
    if not session or not user:
        raise HTTPException(status_code=401, detail="invalid_credentials")
    user_meta = getattr(user, "user_metadata", None) or {}
    intent_value = user_meta.get("intent") if isinstance(user_meta, dict) else None
    return AuthLoginResponse(access_token=session.access_token, refresh_token=session.refresh_token, expires_at=int(getattr(session, "expires_at", 0) or 0), user_id=user.id, email=user.email, intent=intent_value)


class IntentUpdateRequest(BaseModel):
    intent: str = Field(min_length=1, max_length=32)


class IntentUpdateResponse(BaseModel):
    intent: str


@app.post("/api/auth/intent", response_model=IntentUpdateResponse)
def auth_update_intent(body: IntentUpdateRequest, authorization: str | None = Header(default=None)):
    """Update the authenticated user's preferred role (intent) in Supabase user metadata."""
    new_intent = (body.intent or "").strip().lower()
    if new_intent not in ("user", "provider"):
        raise HTTPException(status_code=400, detail="invalid_intent")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing_token")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="missing_token")
    supabase = get_supabase_client()
    try:
        user_resp = supabase.auth.get_user(token)
    except Exception:
        logging.exception("auth_intent_get_user_failed")
        raise HTTPException(status_code=401, detail="invalid_token")
    user = getattr(user_resp, "user", None)
    if not user or not getattr(user, "id", None):
        raise HTTPException(status_code=401, detail="invalid_token")
    existing_meta = getattr(user, "user_metadata", None) or {}
    if not isinstance(existing_meta, dict):
        existing_meta = {}
    merged_meta = dict(existing_meta)
    merged_meta["intent"] = new_intent
    try:
        supabase.auth.admin.update_user_by_id(user.id, {"user_metadata": merged_meta})
    except Exception:
        logging.exception("auth_intent_update_failed")
        raise HTTPException(status_code=502, detail="intent_update_failed")
    return IntentUpdateResponse(intent=new_intent)


@app.post("/api/auth/magic-link")
def auth_magic_link(body: MagicLinkRequest):
    if not EMAILRE.match(body.email):
        raise HTTPException(status_code=400, detail="invalid_email")
    supabase = get_supabase_client()
    try:
        supabase.auth.sign_in_with_otp({"email": body.email, "options": {"should_create_user": False}})
    except Exception:
        logging.exception("magic_link_failed")
    return {"sent": True, "message": "If that email is registered, a magic link has been sent."}

import urllib.request as _urlreq
import urllib.error as _urlerr


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    stream: bool = False


class ChatResponse(BaseModel):
    answer: str


@app.post("/api/chat", response_model=ChatResponse)
def chat(body: ChatRequest):
    sf_key = os.environ.get("SILICONFLOW_API_KEY")
    SILICONFLOW_MODEL = os.environ.get("SILICONFLOW_MODEL", "deepseek-ai/DeepSeek-V3.1")
    if not sf_key:
        raise HTTPException(status_code=503, detail="chat_not_configured")
    if not body.messages:
        raise HTTPException(status_code=400, detail="messages_required")
    payload = json.dumps({
        "model": SILICONFLOW_MODEL,
        "messages": [{"role": m.role, "content": m.content} for m in body.messages],
        "stream": False,
    }).encode("utf-8")
    req = _urlreq.Request(
        "https://api.siliconflow.com/v1/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {sf_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _urlreq.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except _urlerr.HTTPError as e:
        logging.exception("sf_http_error")
        raise HTTPException(status_code=502, detail="inference_failed")
    except Exception:
        logging.exception("sf_call_failed")
        raise HTTPException(status_code=502, detail="inference_failed")
    try:
        answer = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise HTTPException(status_code=502, detail="empty_response")
    if not answer:
        raise HTTPException(status_code=502, detail="empty_response")
    return ChatResponse(answer=answer)




app.mount("/dashboard", StaticFiles(directory="dashboard", html=True), name="dashboard")


# Wire in /api/agents endpoints
from agents import router as _agents_router
app.include_router(_agents_router)
