# Stripe live setup for NeuralMesh Beta

## Create the beta product and price
1. Open Stripe Dashboard and switch the top-left mode toggle to **Live**.
2. Go to **Product catalog**.
3. Click **Add product**.
4. Name it `NeuralMesh Beta`.
5. Add description: `$19/month, 5000 requests/day, priority routing`.
6. Under pricing, choose **Recurring**.
7. Set price to `19.00 USD`.
8. Set billing period to **Monthly**.
9. Save the product.
10. Copy the live Product ID into `STRIPE_BETA_PRODUCT_ID`.
11. Copy the live Price ID into `STRIPE_BETA_PRICE_ID`.

## Register the webhook
1. Go to **Developers > Webhooks**.
2. Click **Add endpoint**.
3. Endpoint URL: `https://api.beta.neuralmesh.ai/webhooks/stripe`.
4. Select events:
   - `checkout.session.completed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
5. Save the endpoint.
6. Reveal the signing secret and set it as `STRIPE_WEBHOOK_SECRET`.

## Customer portal
1. Go to **Settings > Billing > Customer portal**.
2. Enable subscription cancellation.
3. Enable invoice history.
4. Set return URL to `https://beta.neuralmesh.ai/account.html`.
5. Save changes.

