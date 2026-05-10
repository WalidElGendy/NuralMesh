# NeuralMesh

## Cursor Cloud specific instructions

### Codebase overview

This is a monorepo with two products:

1. **Simple Inference API** (root-level `api.py` / `node.py`) — FastAPI app requiring Supabase for job queue and billing. Not runnable without external Supabase credentials.
2. **Smart Orchestrator** (`smart_orchestrator/`) — The main development target. FastAPI service with a 7-stage inference pipeline (classify → cache → prune → compress → route → verify → settle). Uses Redis, Qdrant, and PostgreSQL as backing services via Docker Compose.

### Running services

Backing services (from `smart_orchestrator/docker-compose.yml`):
```bash
cd smart_orchestrator && docker compose up -d redis qdrant postgres
```

Dev server (Smart Orchestrator):
```bash
cd smart_orchestrator
source .venv/bin/activate
ROUTE_MODEL_PREFIX=mock AUTH_ENABLED=false uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- `ROUTE_MODEL_PREFIX=mock` avoids real LLM API calls (no Ollama or frontier API keys required).
- `AUTH_ENABLED=false` disables API key auth for local development. With auth enabled, requests need an `X-Api-Key` header.
- Health check: `curl http://127.0.0.1:8000/health`

### Testing

```bash
cd smart_orchestrator && source .venv/bin/activate
python -m pytest tests/ -v
```

All 130 tests pass with mocks (no external services needed for unit tests). The test suite uses `fakeredis` for Redis mocking.

### Linting

```bash
cd smart_orchestrator && source .venv/bin/activate
ruff check .
```

Ruff is configured in `smart_orchestrator/pyproject.toml` (line-length=100, target Python 3.11).

### Gotchas

- `pyproject.toml` does not list `prometheus_client`, `fakeredis`, or `stripe` as dependencies, but the codebase imports them. They must be installed separately: `pip install prometheus_client fakeredis stripe`.
- The root-level Simple API (`api.py`) requires `SUPABASE_URL` and `SUPABASE_KEY` environment variables and cannot run without a real Supabase instance.
- Docker must be running before starting the dev server (Redis is required for health checks and rate limiting).
- Observability (OpenTelemetry/Loki) is disabled by default via `OTEL_ENABLED=false` and `LOKI_ENABLED=false`.
