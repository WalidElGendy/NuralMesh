import os
import random
import socket
import subprocess
import time
import logging
from pathlib import Path

import ollama
import requests


DEFAULT_NODE_MODEL = "llama3.3:70b-instruct-q4_K_M"
NODE_MODEL = os.environ.get("NM_NODE_MODEL", DEFAULT_NODE_MODEL)
NODE_MODELS = [
    model.strip()
    for model in os.environ.get("NM_NODE_MODELS", NODE_MODEL).split(",")
    if model.strip()
]
POLL_INTERVAL_SECONDS = 3
POLL_JITTER_SECONDS = 1
MIN_FREE_VRAM_MB = 22 * 1024
DEFAULT_API_BASE_URL = "https://api.beta.meshnet.co"
CREDENTIALS_FILE = Path(os.environ.get("MESHNET_CREDENTIALS_FILE", "~/.meshnet/credentials")).expanduser()

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
    if not check_ollama_models():
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


def read_credentials(path=CREDENTIALS_FILE):
    credentials = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line or line.strip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            credentials[key.strip()] = value.strip().strip('"')
    for key in ("NODE_ID", "NODE_SECRET"):
        if os.environ.get(key):
            credentials[key] = os.environ[key]
    return credentials


def get_required_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def build_session(node_id, node_secret):
    session = requests.Session()
    session.headers.update(
        {
            "X-Node-Id": node_id,
            "X-Node-Secret": node_secret,
            "User-Agent": "meshnet-node/0.1",
        }
    )
    return session


def heartbeat(session, api_base_url, gpu_info=None):
    response = session.post(
        f"{api_base_url}/api/node/heartbeat",
        json={"hostname": socket.gethostname(), "gpu_info": gpu_info or {}},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def claim_pending_job(session, api_base_url):
    response = session.get(f"{api_base_url}/api/node/jobs/next", timeout=30)
    response.raise_for_status()
    return response.json().get("job")


def complete_job(session, api_base_url, job_id, inference):
    payload = {
        "status": "complete",
        "output": inference["content"],
        "model": inference["model"],
        "latency_ms": inference["latency_ms"],
        "prompt_tokens": inference["prompt_tokens"],
        "completion_tokens": inference["completion_tokens"],
        "total_tokens": inference["total_tokens"],
        "tokens_served": inference["total_tokens"],
    }
    response = session.post(
        f"{api_base_url}/api/node/jobs/{job_id}/complete",
        json=payload,
        timeout=30,
    )
    response.raise_for_status()


def mark_job_error(session, api_base_url, job_id, error):
    response = session.post(
        f"{api_base_url}/api/node/jobs/{job_id}/error",
        json={"error": str(error)},
        timeout=30,
    )
    response.raise_for_status()


def process_job(session, api_base_url, job):
    try:
        inference = run_inference(job["prompt"])
    except Exception as error:
        mark_job_error(session, api_base_url, job["id"], error)
        print(f"Job {job['id']} failed: {error}")
        return

    complete_job(session, api_base_url, job["id"], inference)
    print(
        f"Job {job['id']} complete "
        f"latency_ms={inference['latency_ms']} total_tokens={inference['total_tokens']}"
    )


def poll_for_jobs():
    credentials = read_credentials()
    node_id = credentials.get("NODE_ID")
    node_secret = credentials.get("NODE_SECRET")
    if not node_id or not node_secret:
        raise RuntimeError(f"Missing NODE_ID or NODE_SECRET in {CREDENTIALS_FILE}")
    api_base_url = os.environ.get("MESHNET_API_BASE_URL", DEFAULT_API_BASE_URL).rstrip("/")
    session = build_session(node_id, node_secret)
    try:
        heartbeat(session, api_base_url)
        print(f"Node {node_id} is online and polling {api_base_url}...")
    except Exception as error:
        print(f"Initial heartbeat failed, will retry in loop: {error}")

    while True:
        try:
            heartbeat(session, api_base_url)
            job = claim_pending_job(session, api_base_url)
            if job:
                print(f"Claimed job {job['id']}")
                process_job(session, api_base_url, job)
        except Exception as error:
            print(f"Polling error: {error}")

        time.sleep(POLL_INTERVAL_SECONDS + random.uniform(0, POLL_JITTER_SECONDS))


if __name__ == "__main__":
    startup_self_check()
    poll_for_jobs()
