# Vercel beta frontend setup

## Create the project

1. Open Vercel.
2. Click **Add New...**.
3. Click **Project**.
4. Import the NeuralMesh GitHub repository.
5. Set **Framework Preset** = **Other**.
6. Set **Build Command** = `node scripts/inject-env.js`.
7. Set **Output Directory** = `web`.
8. Click **Deploy**.

## Paste environment variables

1. Open the Vercel project.
2. Click **Settings**.
3. Click **Environment Variables**.
4. Add `NM_API_BASE` = `https://api.beta.meshnet.co`.
5. Add `NM_SUPABASE_URL` from Supabase **Project Settings** -> **API**.
6. Add `NM_SUPABASE_ANON_KEY` from Supabase **Project Settings** -> **API**.
7. Select **Production**, **Preview**, and **Development** unless a narrower scope is intentional.
8. Click **Save** after each variable.
9. Click **Deployments**.
10. Click the latest deployment menu.
11. Click **Redeploy**.

## Add beta.meshnet.co

1. Click **Settings**.
2. Click **Domains**.
3. Type `beta.meshnet.co`.
4. Click **Add**.
5. Confirm Vercel asks for `CNAME cname.vercel-dns.com`.
6. Add the DNS record at the DNS provider.
7. Wait for **Valid Configuration**.
8. Open `https://beta.meshnet.co`.
9. Confirm the hero reads `Get Llama 3.3 70B inference on the sovereign GPU mesh`.
