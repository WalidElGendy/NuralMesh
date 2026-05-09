# Beta launch checklist

1. Create a new Supabase project named `neuralmesh-beta`.
2. Copy `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY`, and `DATABASE_URL`.
3. Run all production migrations in ascending order, including `003`, `020`, and `021`.
4. Seed initial invites with `python scripts/seed_beta_invites.py --count 50 --notes "Initial beta launch invites"`.
5. Create or confirm beta Redis and Qdrant services.
6. Open Render and create the `neuralmesh-beta-api` Blueprint from `render.yaml`.
7. Paste every Render environment variable from `config/beta.env.example`.
8. Deploy the Render service.
9. Add Render custom domains `api.beta.meshnet.co` and `install.beta.meshnet.co`.
10. Open Vercel and import the repository as the beta frontend project.
11. Confirm Vercel build command is `node scripts/inject-env.js`.
12. Confirm Vercel output directory is `web`.
13. Paste Vercel env vars `NM_API_BASE`, `NM_SUPABASE_URL`, and `NM_SUPABASE_ANON_KEY`.
14. Deploy Vercel.
15. Add Vercel custom domain `beta.meshnet.co`.
16. Open Cloudflare DNS for `meshnet.co`.
17. Add `beta` CNAME to `cname.vercel-dns.com`.
18. Add `api` CNAME to `<render-app-name>.onrender.com`.
19. Add `install` CNAME to `<render-app-name>.onrender.com`.
20. Set Cloudflare SSL/TLS mode to **Full**.
21. Wait for Vercel domain verification to show **Valid Configuration**.
22. Wait for Render custom domains to show **Certificate Issued**.
23. Open `https://beta.meshnet.co` and confirm the beta hero renders.
24. Open `https://api.beta.meshnet.co/health` and confirm `status` is `ok`.
25. Open `https://api.beta.meshnet.co/readyz` and confirm `status` is `ok`.
