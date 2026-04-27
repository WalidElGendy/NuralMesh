import os
import random
import time

import ollama
from supabase import create_client


POLL_INTERVAL_SECONDS = 3
POLL_JITTER_SECONDS = 1
PENDING_JOB_LIMIT = 10


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
        .limit(PENDING_JOB_LIMIT)
        .execute()
    )

    if not pending_jobs.data:
        return None

    for job in pending_jobs.data:
        # This conditional update is the distributed lock: only one node can
        # change a pending row to processing, even if many nodes saw it.
        claimed_job = (
            supabase.table("jobs")
            .update({"status": "processing", "node_id": node_id})
            .eq("id", job["id"])
            .eq("status", "pending")
            .execute()
        )

        if claimed_job.data:
            return claimed_job.data[0]

    return None


def complete_job(supabase, job_id, node_id, output):
    result = supabase.table("jobs").update(
        {
            "status": "complete",
            "output": output,
        }
    ).eq("id", job_id).eq("node_id", node_id).eq("status", "processing").execute()

    return bool(result.data)


def mark_job_error(supabase, job_id, node_id, error):
    result = supabase.table("jobs").update(
        {
            "status": "error",
            "output": f"Inference failed: {error}",
        }
    ).eq("id", job_id).eq("node_id", node_id).eq("status", "processing").execute()

    return bool(result.data)


def process_job(supabase, job, node_id):
    try:
        output = run_inference(job["prompt"])
    except Exception as error:
        if mark_job_error(supabase, job["id"], node_id, error):
            print(f"Job {job['id']} failed: {error}")
        else:
            print(f"Job {job['id']} failed, but this node no longer owns it")
        return

    if complete_job(supabase, job["id"], node_id, output):
        print(f"Job {job['id']} complete")
    else:
        print(f"Job {job['id']} finished, but this node no longer owns it")


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
                process_job(supabase, job, node_id)
        except Exception as error:
            print(f"Polling error: {error}")

        time.sleep(POLL_INTERVAL_SECONDS + random.uniform(0, POLL_JITTER_SECONDS))


if __name__ == "__main__":
    poll_for_jobs()
