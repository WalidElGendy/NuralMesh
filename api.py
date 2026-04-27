import os

import stripe
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from supabase import create_client


app = FastAPI(title="Distributed AI Inference API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    supabase_key = get_required_env("SUPABASE_KEY")
    return create_client(supabase_url, supabase_key)


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


@app.get("/")
def health_check():
    return {"status": "ok"}


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
