# Stripe Live Mode Setup

## 1. Create Live Products in Stripe Dashboard
1. Go to https://dashboard.stripe.com/products
2. Create three products matching your plans:
   - **Free**  $0/month, set env `STRIPE_FREE_PRICE_ID=price_xxx`
   - **Pro**  $29/month, set env `STRIPE_PRO_PRICE_ID=price_xxx`
   - **Admin**  $99/month, set env `STRIPE_ADMIN_PRICE_ID=price_xxx`
3. Copy each Price ID and add to Render env vars (see below).

## 2. Live Secret Key in Render
1. Stripe Dashboard  Developers  API keys  copy **Secret key** (starts with `sk_live_`)
2. Render  your service  Environment  Add: `STRIPE_SECRET_KEY=sk_live_xxx`
3. Also set: `STRIPE_MODE=live`

## 3. Register Production Webhook
1. Stripe Dashboard  Developers  Webhooks  Add endpoint
2. Endpoint URL: `https://YOUR_RENDER_URL/webhooks/stripe`
3. Events: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`
4. Save  copy **Signing secret** (starts with `whsec_`)
5. Render env var: `STRIPE_WEBHOOK_SECRET=whsec_xxx`

## 4. Test a Live $1 Transaction
1. Create a test product at $1 in live mode
2. Open checkout link in a private browser window
3. Pay with a real card
4. Verify webhook fires (Stripe dashboard  Webhooks  recent)
5. Refund: Stripe Dashboard  Payments  find payment  Refund
