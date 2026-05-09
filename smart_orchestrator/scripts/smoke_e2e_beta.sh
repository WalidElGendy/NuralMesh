#!/usr/bin/env bash
set -euo pipefail

API_BASE="${1:-${API_BASE:-http://localhost:8000}}"
ADMIN_SECRET="${ADMIN_SECRET:-change-me-in-prod}"
EMAIL="${SMOKE_EMAIL:-beta-smoke+$(date +%s)@example.com}"
PASSWORD="${SMOKE_PASSWORD:-correct-horse-battery}"
COOKIE_JAR="$(mktemp)"

cleanup() {
  rm -f "$COOKIE_JAR"
}
trap cleanup EXIT

echo "==> Beta smoke test against $API_BASE"

INVITE=$(curl -sf -X POST "$API_BASE/api/admin/seed-invites" \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: $ADMIN_SECRET" \
  -d '{"count":1,"created_by":"smoke"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["invites"][0]["code"])')
echo "OK: seeded invite $INVITE"

SIGNUP=$(curl -sf -X POST "$API_BASE/api/auth/signup" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"invite_code\":\"$INVITE\",\"intent\":\"user\"}")
CONFIRM_URL=$(echo "$SIGNUP" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("confirmation_url",""))')
test -n "$CONFIRM_URL"
echo "OK: signup created confirmation link"

curl -sf -L -c "$COOKIE_JAR" "$CONFIRM_URL" >/dev/null
echo "OK: confirmed email"

curl -sf -c "$COOKIE_JAR" -b "$COOKIE_JAR" -X POST "$API_BASE/api/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" >/dev/null
CSRF=$(python3 - "$COOKIE_JAR" <<'PY'
import sys
for line in open(sys.argv[1]):
    if "nm_csrf" in line:
        print(line.strip().split("\t")[-1])
PY
)
test -n "$CSRF"
echo "OK: logged in and captured CSRF"

CHAT=$(curl -sf -b "$COOKIE_JAR" -X POST "$API_BASE/api/chat" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{"stream":false,"messages":[{"role":"user","content":"What is 2+2?"}]}')
echo "$CHAT" | python3 -c 'import json,sys; assert json.load(sys.stdin).get("answer") is not None'
echo "OK: chat works during free trial"

CHECKOUT=$(curl -sf -b "$COOKIE_JAR" -X POST "$API_BASE/api/billing/create-checkout-session" \
  -H "X-CSRF-Token: $CSRF")
echo "$CHECKOUT" | python3 -c 'import json,sys; assert json.load(sys.stdin).get("checkout_url")'
echo "OK: checkout URL returned"

USER_ID=$(curl -sf -b "$COOKIE_JAR" "$API_BASE/api/me" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
EVENT="{\"type\":\"checkout.session.completed\",\"data\":{\"object\":{\"client_reference_id\":\"$USER_ID\",\"customer\":\"cus_smoke\",\"subscription\":\"sub_smoke\",\"metadata\":{\"user_id\":\"$USER_ID\"}}}}"
curl -sf -X POST "$API_BASE/webhooks/stripe" \
  -H "Content-Type: application/json" \
  -H "stripe-signature: mock" \
  -d "$EVENT" >/dev/null
curl -sf -b "$COOKIE_JAR" "$API_BASE/api/me" | python3 -c 'import json,sys; assert json.load(sys.stdin)["subscription_status"] == "active"'
echo "OK: checkout webhook activated subscription"

CHAT_AFTER=$(curl -sf -b "$COOKIE_JAR" -X POST "$API_BASE/api/chat" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  -d '{"stream":false,"messages":[{"role":"user","content":"Say subscription is active."}]}')
echo "$CHAT_AFTER" | python3 -c 'import json,sys; assert json.load(sys.stdin).get("answer") is not None'
echo "OK: chat works after subscription"

echo "OK: beta smoke test completed"
