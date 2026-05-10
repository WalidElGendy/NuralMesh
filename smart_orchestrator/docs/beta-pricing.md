# Beta pricing and trial

## Plan
- Name: `NeuralMesh Beta`
- Price: `$19/month`
- Included usage: `5000 requests/day`
- Routing: priority routing

## Free trial
- New AI users get `50` requests.
- Trial requests must be used during the first `7` days from signup.
- When the user is over either trial boundary and is not subscribed, `POST /api/chat` returns:
  - HTTP `402`
  - `{ "message": "Subscribe to continue", "checkout_url": "..." }`

## Providers
- Providers do not subscribe.
- Providers must accept the beta participation agreement before claiming or operating beta nodes.

