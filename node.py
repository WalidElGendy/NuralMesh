import os
import random
import subprocess
import time
import logging

import ollama
from supabase import create_client


DEFAULT_NODE_MODEL = "llama3.3:70b-instruct-q4_K_M"
NODE_MODEL = os.environ.get("NM_NODE_MODEL", DEFAULT_NODE_MODEL)
NODE_MODELS = [
    model.strip()
    for model in os.environ.get("NM_NODE_MODELS", NODE_MODEL).split(",")
    if model.strip()
]
POLL_INTERVAL_SECONDS = 3
POLL_JITTER_SECONDS = 1
PENDING_JOB_LIMIT = 10
MIN_FREE_VRAM_MB = 22 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s [NODE] %(message)s")
logger = logging.getLogger(__name__)


def _model_names(response):
    models = response.get("models", []) if isinstance(response, dict) else getattr(response, "models", [])
    names = set()
    for model in models:
        if isinstance(model, dict):
            names.add(model.get("name", ""))
        else:
            names.add(getattr(model, "model", "") or getattr(model, "name", ""))
    return names


def check_ollama_models():
    try:
        installed = _model_names(ollama.list())
    except Exception as error:
        logger.error("Ollama self-check failed: %s", error)
        return False

    missing = [model for model in NODE_MODELS if model not in installed]
    if missing:
        logger.error("Required Ollama model(s) not pulled: %s", ", ".join(missing))
        return False
    return True


def check_gpu_memory():
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.free",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as error:
        logger.error("GPU memory self-check failed: %s", error)
        return False

    free_values = [int(value.strip()) for value in result.stdout.splitlines() if value.strip()]
    if not free_values:
        logger.error("GPU memory self-check returned no GPU rows")
        return False
    max_free_mb = max(free_values)
    if max_free_mb < MIN_FREE_VRAM_MB:
        logger.warning("Free GPU VRAM is below 22GB: %.2fGB", max_free_mb / 1024)
    return True


def startup_self_check():
    if not check_ollama_models() or not check_gpu_memory():
        logger.error("Node startup self-check failed; exiting")
        raise SystemExit(1)


def run_inference(prompt):
    start = time.perf_counter()
    response = ollama.chat(
        model=NODE_MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
    )
    content = response["message"]["content"]
    prompt_tokens = int(response.get("prompt_eval_count", 0) or max(1, len(prompt.split())))
    completion_tokens = int(response.get("eval_count", 0) or max(1, len(content.split())))
    return {
        "content": content,
        "model": NODE_MODEL,
        "latency_ms": int((time.perf_counter() - start) * 1000),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


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


def complete_job(supabase, job_id, node_id, inference):
    result = supabase.table("jobs").update(
        {
            "status": "complete",
            "output": inference["content"],
            "model": inference["model"],
            "latency_ms": inference["latency_ms"],
            "prompt_tokens": inference["prompt_tokens"],
            "completion_tokens": inference["completion_tokens"],
            "total_tokens": inference["total_tokens"],
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
        inference = run_inference(job["prompt"])
    except Exception as error:
        if mark_job_error(supabase, job["id"], node_id, error):
            print(f"Job {job['id']} failed: {error}")
        else:
            print(f"Job {job['id']} failed, but this node no longer owns it")
        return

    if complete_job(supabase, job["id"], node_id, inference):
        print(
            f"Job {job['id']} complete "
            f"latency_ms={inference['latency_ms']} total_tokens={inference['total_tokens']}"
        )
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
    startup_self_check()
    poll_for_jobs()
