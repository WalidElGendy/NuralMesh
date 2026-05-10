# NeuralMesh Smart Orchestrator

Sprint 1 implementation of the NeuralMesh Smart Orchestrator: an async, mocked end-to-end inference pipeline that classifies prompts, checks semantic cache, prunes history, compresses prompts, routes across a model ladder, verifies outputs, and settles job/provider/billing records.

## What works in Sprint 1

- `POST /chat` streams Server-Sent Events for all pipeline stages, token chunks, and final job metadata.
- All Provider node dispatch is mocked in `app/lib/mesh_dispatch.py`.
- Local mesh models are mocked.
- Frontier models use LiteLLM only when relevant API keys are present; otherwise they fall back to mocks.
- Eval datasets include 50 prompts per domain across code, creative, factual, reasoning, math, and chat.
- Eval harness runs baseline and orchestrator configs with mocked judging.
- Docker Compose includes Qdrant, Redis 7, and PostgreSQL 16 for future backing services.

## Setup

```bash
cd smart_orchestrator
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
docker compose up -d
uvicorn app.main:app --reload
```

## Try `/chat`

```bash
curl -N http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "subscriber_id": "sub_demo_pro",
    "system": "You are concise.",
    "stream": true,
    "messages": [
      {"role": "user", "content": "Write a Python function that validates email addresses."}
    ]
  }'
```

## Run eval

```bash
PYTHONPATH=. python -m app.eval.run_eval
```

## Architecture

The pipeline passes a `PipelineContext` through seven stages:

1. Classify
2. Cache
3. Prune
4. Compress
5. Route
6. Verify
7. Settle

Secrets are read from environment variables only. Prompt bodies are not logged at INFO level.


## Soft launch checklist

Every env var that must be set in production for the system to actually work:

### Render (backend)
| Env Var | Description | Required |
|---|---|---|
|  | Stripe live secret key () | Yes |
|  | Webhook signing secret () | Yes |
|  | Set to  | Yes |
|  | Stripe price ID for Free plan | Yes |
|  | Stripe price ID for Pro plan | Yes |
|  | Stripe price ID for Admin plan | Yes |
|  | Resend API key for waitlist emails | Yes |
|  | Sender address, e.g.  | Yes |
|  | Secret for  | Yes |
|  | Your Supabase project URL | Yes |
|  | Supabase service role key | Yes |
|  | Redis connection string | Yes |
|  | Qdrant vector store URL | Yes |
|  | Secret for  endpoints | Yes |
|  | DeepSeek model identifier | Yes (if using) |
|  | Anthropic model identifier | Yes (if using) |
|  | Google Gemini model identifier | Yes (if using) |
|  | Ollama Llama model path | Yes (if using) |
|  |  to enable tracing | Optional |

### Vercel (landing + dashboard)
| Env Var | Description |
|---|---|
|  | Backend URL from Render |
|  | Supabase URL |
|  | Supabase anon key |

### Supabase (database)
- Run migrations 001-006 in order
- Configure Database Webhook for  and  INSERT events
  pointing to  with  header
