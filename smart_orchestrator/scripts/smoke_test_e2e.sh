#!/usr/bin/env bash
# smoke_test_e2e.sh  End-to-end smoke test
# Usage: API_BASE=https://your-api.onrender.com ./scripts/smoke_test_e2e.sh
# Or:    ./scripts/smoke_test_e2e.sh https://your-api.onrender.com

set -euo pipefail

API_BASE="${1:-${API_BASE:-http://localhost:8000}}"
API_KEY="${SMOKE_API_KEY:-test-key}"

echo "==> Smoke test against $API_BASE"

# 1. Health check
echo "--- /health ---"
HEALTH=$(curl -sf "$API_BASE/health")
echo "$HEALTH"
echo "$HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('status')=='ok', f'health not ok: {d}'"
echo "OK: /health"

# 2. Submit a job
echo "--- /submit ---"
JOB=$(curl -sf -X POST "$API_BASE/submit" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"prompt": "What is 2+2?", "intent": "math"}')
echo "$JOB"
JOB_ID=$(echo "$JOB" | python3 -c "import sys,json; print(json.load(sys.stdin).get('job_id',''))")
if [ -z "$JOB_ID" ]; then
  echo "WARN: no job_id returned  using /chat fallback"
  RESULT=$(curl -sf "$API_BASE/chat" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $API_KEY" \
    -d '{"prompt": "What is 2+2?"}')
  echo "$RESULT"
  echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('response'), 'empty response'"
  echo "OK: /chat response non-empty"
  exit 0
fi
echo "OK: /submit job_id=$JOB_ID"

# 3. Poll until complete
echo "--- /job/$JOB_ID ---"
for i in $(seq 1 20); do
  RESULT=$(curl -sf "$API_BASE/job/$JOB_ID" -H "X-API-Key: $API_KEY" 2>/dev/null || echo '{}')
  STATUS=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
  echo "  poll $i: status=$STATUS"
  if [ "$STATUS" = "complete" ] || [ "$STATUS" = "done" ]; then
    echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('response') or d.get('result'), 'empty result'"
    echo "OK: /job/$JOB_ID completed with non-empty response"
    exit 0
  fi
  sleep 3
done
echo "FAIL: job $JOB_ID did not complete in 60s"
exit 1
