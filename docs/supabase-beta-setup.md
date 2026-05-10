# Supabase beta production setup

Create a new Supabase project specifically for beta. Do not reuse staging, prelaunch, or waitlist databases.

## Create the project

1. Open Supabase.
2. Click **New project**.
3. Choose the production organization.
4. Enter **Name** = `neuralmesh-beta`.
5. Generate and save a strong database password.
6. Choose the closest region to the Render backend.
7. Click **Create new project**.
8. Wait for the project to become active.

## Capture values

1. Click **Project Settings**.
2. Click **API**.
3. Copy **Project URL** into `SUPABASE_URL`.
4. Copy **service_role secret** into `SUPABASE_SERVICE_ROLE_KEY` for Render only.
5. Copy **anon public** into `SUPABASE_ANON_KEY` for Render and Vercel.
6. Click **Database**.
7. Copy the production connection string into `DATABASE_URL`.

## Run migrations

Run all production migrations `001` through `099` in ascending order. This repo currently includes:

1. `migrations/003_add_billing_tables.sql`
2. `migrations/020_beta_users_and_providers.sql`
3. `migrations/021_beta_invites.sql`

To run each file:

1. Click **SQL Editor**.
2. Click **New query**.
3. Paste the SQL file contents.
4. Click **Run**.
5. Confirm the query succeeds.
6. Repeat for the next migration number.

## Seed initial beta invites

From a trusted local shell with beta Supabase env vars loaded:

`python scripts/seed_beta_invites.py --count 50 --notes "Initial beta launch invites"`

Confirm rows appear in the `invites` table before opening signup.
