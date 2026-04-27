import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from supabase import create_client


app = FastAPI(title="Distributed AI Inference API")


class JobRequest(BaseModel):
    prompt: str = Field(..., min_length=1)


def get_required_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def get_supabase_client():
    supabase_url = get_required_env("SUPABASE_URL")
    supabase_key = get_required_env("SUPABASE_KEY")
    return create_client(supabase_url, supabase_key)


@app.get("/")
def health_check():
    return {"status": "ok"}


@app.post("/jobs")
def submit_job(job_request: JobRequest):
    try:
        result = (
            get_supabase_client()
            .table("jobs")
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

    return result.data[0]


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    try:
        result = (
            get_supabase_client()
            .table("jobs")
            .select("*")
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

    return result.data[0]
