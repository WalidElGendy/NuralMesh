import os
import time

import ollama
from supabase import create_client


POLL_INTERVAL_SECONDS = 3


def run_inference(prompt):
    response = ollama.chat(
        model="llama3",
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
    )
    return response["message"]["content"]


def get_required_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def claim_pending_job(supabase, node_id):
    pending_jobs = (
        supabase.table("jobs")
        .select("*")
        .eq("status", "pending")
        .limit(1)
        .execute()
    )

    if not pending_jobs.data:
        return None

    job = pending_jobs.data[0]
    claimed_job = (
        supabase.table("jobs")
        .update({"status": "processing", "node_id": node_id})
        .eq("id", job["id"])
        .eq("status", "pending")
        .execute()
    )

    if not claimed_job.data:
        return None

    return claimed_job.data[0]


def complete_job(supabase, job_id, output):
    supabase.table("jobs").update(
        {
            "status": "complete",
            "output": output,
        }
    ).eq("id", job_id).execute()


def mark_job_error(supabase, job_id, error):
    supabase.table("jobs").update(
        {
            "status": "error",
            "output": f"Inference failed: {error}",
        }
    ).eq("id", job_id).execute()


def process_job(supabase, job):
    try:
        output = run_inference(job["prompt"])
    except Exception as error:
        mark_job_error(supabase, job["id"], error)
        print(f"Job {job['id']} failed: {error}")
        return

    complete_job(supabase, job["id"], output)
    print(f"Job {job['id']} complete")


def poll_for_jobs():
    supabase_url = get_required_env("SUPABASE_URL")
    supabase_key = get_required_env("SUPABASE_KEY")
    node_id = get_required_env("NODE_ID")
    supabase = create_client(supabase_url, supabase_key)

    print(f"Node {node_id} is polling for jobs...")

    while True:
        try:
            job = claim_pending_job(supabase, node_id)
            if job:
                print(f"Claimed job {job['id']}")
                process_job(supabase, job)
        except Exception as error:
            print(f"Polling error: {error}")

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    poll_for_jobs()
