# DNS and SSL setup for beta.meshnet.co

## Records to create

Replace `<render-app-name>` with the Render service hostname shown in Render after deploy.

| Name | Type | Target | Notes |
| --- | --- | --- | --- |
| `beta.meshnet.co` | CNAME | `cname.vercel-dns.com` | Use Cloudflare proxy if Cloudflare is authoritative DNS; otherwise plain CNAME. |
| `api.beta.meshnet.co` | CNAME | `<render-app-name>.onrender.com` | Render custom domain for the FastAPI backend. |
| `install.beta.meshnet.co` | CNAME | `<render-app-name>.onrender.com` | Reserved for the Sprint D bash installer. |

## Cloudflare as DNS

1. Open Cloudflare.
2. Click **Websites**.
3. Click **meshnet.co**.
4. Click **DNS**.
5. Click **Records**.
6. Click **Add record**.
7. Choose **Type** = `CNAME`.
8. Enter **Name** = `beta`.
9. Enter **Target** = `cname.vercel-dns.com`.
10. Leave **Proxy status** = **Proxied** if Cloudflare is the active DNS provider; use **DNS only** if Vercel asks for DNS-only during verification.
11. Click **Save**.
12. Repeat for **Name** = `api`, **Target** = `<render-app-name>.onrender.com`.
13. Repeat for **Name** = `install`, **Target** = `<render-app-name>.onrender.com`.
14. Click **SSL/TLS**.
15. Set **SSL/TLS encryption mode** = **Full**.

## Vercel domain verification

1. Open Vercel.
2. Click the NeuralMesh beta project.
3. Click **Settings**.
4. Click **Domains**.
5. Type `beta.meshnet.co`.
6. Click **Add**.
7. Confirm Vercel shows `CNAME cname.vercel-dns.com`.
8. Wait until Vercel shows **Valid Configuration**.
9. Open `https://beta.meshnet.co`.
10. Confirm the browser lock icon is present.

## Render custom domains

1. Open Render.
2. Click the `neuralmesh-beta-api` web service.
3. Click **Settings**.
4. Scroll to **Custom Domains**.
5. Click **Add Custom Domain**.
6. Enter `api.beta.meshnet.co`.
7. Click **Save**.
8. Repeat for `install.beta.meshnet.co`.
9. Confirm Render shows the expected CNAME target.
10. Wait until Render shows **Certificate Issued**.
11. Open `https://api.beta.meshnet.co/health`.
12. Confirm the response contains `"status":"ok"`.
