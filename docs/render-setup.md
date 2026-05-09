# Render beta backend setup

## Create the service

1. Open Render.
2. Click **New +**.
3. Click **Blueprint**.
4. Connect the GitHub repository.
5. Select the branch that contains `render.yaml`.
6. Click **Apply**.
7. Confirm the service name is `neuralmesh-beta-api`.
8. Confirm **Build Command** is `pip install -r requirements.txt`.
9. Confirm **Start Command** is `uvicorn api:app --host 0.0.0.0 --port $PORT`.
10. Click **Create Blueprint Instance**.

## Paste environment variables

1. Open the `neuralmesh-beta-api` service.
2. Click **Environment**.
3. Click **Add Environment Variable** for each key in `config/beta.env.example`.
4. Paste `NM_ENV` = `production`.
5. Paste `DATABASE_URL` from the Supabase project database connection string.
6. Paste `SUPABASE_URL` from Supabase **Project Settings** -> **API**.
7. Paste `SUPABASE_SERVICE_ROLE_KEY` from Supabase **Project Settings** -> **API**.
8. Paste `SUPABASE_ANON_KEY` from Supabase **Project Settings** -> **API**.
9. Paste `REDIS_URL` from the beta Redis provider.
10. Paste `QDRANT_URL` from the beta Qdrant provider.
11. Paste `STRIPE_SECRET_KEY`.
12. Paste `STRIPE_WEBHOOK_SECRET`.
13. Paste `STRIPE_PRICE_ID_USER_BETA`.
14. Paste `GROQ_API_KEY`.
15. Paste `GROQ_MODEL` = `llama-3.3-70b-versatile`.
16. Paste `AUTH_ENABLED` = `true`.
17. Paste `OTEL_ENABLED` = `true`.
18. Paste `LOKI_ENABLED` = `false`.
19. Paste `ALLOWED_ORIGINS` = `https://beta.meshnet.co`.
20. Paste `INTERNAL_API_KEY`.
21. Paste `RESEND_API_KEY`.
22. Paste `EMAIL_FROM`.
23. Paste `BETA_INVITE_REQUIRED` = `true`.
24. Paste `SENTRY_DSN` or leave it empty.
25. Click **Save Changes**.

## Deploy and verify

1. Click **Manual Deploy**.
2. Click **Deploy latest commit**.
3. Wait for **Live**.
4. Open `https://<render-app-name>.onrender.com/health`.
5. Confirm `status` is `ok`.
6. Open `https://<render-app-name>.onrender.com/readyz`.
7. Confirm `status` is `ok`.
8. Add `api.beta.meshnet.co` and `install.beta.meshnet.co` under **Settings** -> **Custom Domains**.
