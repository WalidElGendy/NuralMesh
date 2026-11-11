// nm-auth-link: magic-link sign-in and password reset for beta.meshnet.co.
//
// The email is sent here (Resend, the same sender as the waitlist welcome)
// rather than by Supabase Auth, with a link to our own page,
// beta.meshnet.co/auth-callback.html, which hands the one-time token back
// here to be exchanged for a session. That keeps the flow independent of the
// project's auth SMTP and redirect-URL settings.
//
// POST JSON, one of:
//   { action: "send", email, kind: "magiclink" | "recovery" }
//       Always answers { sent: true } so it never reveals who has an account.
//       Throttled per address in the database (nm_auth_email_allowed).
//   { action: "verify", token_hash, type }
//       Signs in from a magic link: { access_token, expires_at, email, intent }.
//   { action: "set_password", token_hash, type: "recovery", password }
//       Uses a reset link to set a new password, then signs in (same reply).
//       The link works once, so if the new password is refused (too weak,
//       same as before) the reply carries retry_token, and the page retries
//       with { action: "set_password", retry_token, password }.
const BETA = "https://beta.meshnet.co";
const ALLOWED_ORIGINS = ["https://beta.meshnet.co", "https://meshnet.co", "https://www.meshnet.co"];
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const ANON_KEY = Deno.env.get("SUPABASE_ANON_KEY") || SERVICE_KEY;
const RESEND_API_KEY = Deno.env.get("RESEND_API_KEY");
const FROM = Deno.env.get("WAITLIST_FROM_EMAIL") ?? "MeshNet <beta@meshnet.co>";

function cors(origin: string | null) {
  const allow = origin && (ALLOWED_ORIGINS.includes(origin) || /^http:\/\/localhost(:\d+)?$/.test(origin))
    ? origin : BETA;
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "content-type, authorization, apikey, x-client-info",
    "Vary": "Origin",
  };
}
const json = (body: unknown, status: number, origin: string | null) =>
  new Response(JSON.stringify(body), { status, headers: { ...cors(origin), "Content-Type": "application/json" } });

const service = { "apikey": SERVICE_KEY, "Authorization": "Bearer " + SERVICE_KEY, "Content-Type": "application/json" };

async function allowed(email: string, kind: string): Promise<boolean> {
  const r = await fetch(SUPABASE_URL + "/rest/v1/rpc/nm_auth_email_allowed", {
    method: "POST", headers: service, body: JSON.stringify({ p_email: email, p_kind: kind }),
  });
  return r.ok && (await r.json()) === true;
}

function emailBody(kind: string, link: string) {
  const reset = kind === "recovery";
  const title = reset ? "Reset your MeshNet password" : "Your MeshNet sign-in link";
  const lead = reset
    ? "Someone asked to reset the password for this MeshNet account. Click the button to choose a new one."
    : "Click the button to sign in to MeshNet. No password needed.";
  const cta = reset ? "Choose a new password" : "Sign in to MeshNet";
  const html =
    '<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;color:#111">' +
    "<h2>" + title + "</h2><p>" + lead + "</p>" +
    '<p><a href="' + link + '" style="display:inline-block;background:#8b5cf6;color:#fff;padding:12px 22px;' +
    'border-radius:999px;text-decoration:none;font-weight:bold">' + cta + "</a></p>" +
    '<p style="font-size:13px;color:#555">Or paste this link into your browser:<br><a href="' + link + '">' + link + "</a></p>" +
    '<p style="font-size:12px;color:#888">The link works once and expires in one hour. ' +
    "If you didn't ask for it, you can ignore this email; your account is unchanged.</p></div>";
  const text = title + "\n\n" + lead + "\n\n" + link +
    "\n\nThe link works once and expires in one hour. If you didn't ask for it, ignore this email.";
  return { subject: title, html, text };
}

async function send(email: string, kind: string) {
  if (!(await allowed(email, kind))) return;           // unknown address or throttled: say nothing
  const g = await fetch(SUPABASE_URL + "/auth/v1/admin/generate_link", {
    method: "POST", headers: service, body: JSON.stringify({ type: kind, email }),
  });
  const out = await g.json().catch(() => ({}));
  const hashed = out?.properties?.hashed_token ?? out?.hashed_token;
  const vtype = out?.properties?.verification_type ?? out?.verification_type ?? kind;
  if (!g.ok || !hashed) { console.error("generate_link failed", g.status, out?.msg || out?.error); return; }
  const link = BETA + "/auth-callback.html?token_hash=" + encodeURIComponent(hashed) + "&type=" + encodeURIComponent(vtype);
  const m = emailBody(kind, link);
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { "Authorization": "Bearer " + RESEND_API_KEY, "Content-Type": "application/json" },
    body: JSON.stringify({ from: FROM, to: [email], subject: m.subject, html: m.html, text: m.text }),
  });
  if (!r.ok) console.error("Resend error", kind, r.status, await r.text());
  else console.info("Sent", kind, "link");
}

async function verify(token_hash: string, type: string) {
  const r = await fetch(SUPABASE_URL + "/auth/v1/verify", {
    method: "POST",
    headers: { "apikey": ANON_KEY, "Content-Type": "application/json" },
    body: JSON.stringify({ type, token_hash }),
  });
  const s = await r.json().catch(() => ({}));
  return r.ok && s.access_token ? s : null;
}

const sessionReply = (s: any) => ({
  access_token: s.access_token,
  expires_at: s.expires_at ?? Math.floor(Date.now() / 1000) + Number(s.expires_in || 3600),
  email: s.user?.email ?? null,
  intent: s.user?.user_metadata?.intent ?? null,
});

// Sets the password for the account behind a recovery session token.
async function setPassword(accessToken: string, password: string, origin: string | null, s: any) {
  if (password.length < 8 || password.length > 128) {
    return json({ error: "password_too_short", retry_token: s ? accessToken : undefined }, 400, origin);
  }
  const auth = { "apikey": ANON_KEY, "Authorization": "Bearer " + accessToken, "Content-Type": "application/json" };
  if (!s) {                                   // a retry: the token must still be a live session
    const who = await fetch(SUPABASE_URL + "/auth/v1/user", { headers: auth });
    if (!who.ok) return json({ error: "link_invalid_or_expired" }, 400, origin);
    s = { access_token: accessToken, user: await who.json() };
  }
  const u = await fetch(SUPABASE_URL + "/auth/v1/user", { method: "PUT", headers: auth, body: JSON.stringify({ password }) });
  if (!u.ok) {
    const e = await u.json().catch(() => ({}));
    console.error("password update failed", u.status, e?.error_code || e?.msg);
    const why = String(e?.error_code || e?.msg || "").toLowerCase();
    const code = why.includes("weak") ? "password_too_weak"
      : why.includes("same") || why.includes("different") ? "password_same_as_old"
      : "password_update_failed";
    return json({ error: code, retry_token: accessToken }, 400, origin);
  }
  return json(sessionReply(s), 200, origin);
}

Deno.serve(async (req) => {
  const origin = req.headers.get("origin");
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(origin) });
  if (req.method !== "POST") return json({ error: "method_not_allowed" }, 405, origin);
  try {
    const body = await req.json().catch(() => ({}));
    const action = String(body.action || "");

    if (action === "send") {
      const email = String(body.email || "").trim().toLowerCase();
      const kind = body.kind === "recovery" ? "recovery" : "magiclink";
      if (!EMAIL_RE.test(email) || email.length > 255) return json({ error: "invalid_email" }, 400, origin);
      if (!RESEND_API_KEY) return json({ error: "email_not_configured" }, 503, origin);
      await send(email, kind);
      return json({
        sent: true,
        message: kind === "recovery"
          ? "If that email has an account, we've sent a link to reset your password."
          : "If that email has an account, we've sent you a sign-in link.",
      }, 200, origin);
    }

    if (action === "set_password" && body.retry_token) {
      return await setPassword(String(body.retry_token), String(body.password || ""), origin, null);
    }

    const token_hash = String(body.token_hash || "");
    const type = String(body.type || "");
    if (!token_hash || !["magiclink", "recovery", "email"].includes(type)) {
      return json({ error: "link_invalid_or_expired" }, 400, origin);
    }

    if (action === "verify") {
      const s = await verify(token_hash, type);
      return s ? json(sessionReply(s), 200, origin) : json({ error: "link_invalid_or_expired" }, 400, origin);
    }

    if (action === "set_password") {
      const password = String(body.password || "");
      if (type !== "recovery") return json({ error: "link_invalid_or_expired" }, 400, origin);
      if (password.length < 8 || password.length > 128) return json({ error: "password_too_short" }, 400, origin);
      const s = await verify(token_hash, type);
      if (!s) return json({ error: "link_invalid_or_expired" }, 400, origin);
      return await setPassword(s.access_token, password, origin, s);
    }

    return json({ error: "unknown_action" }, 400, origin);
  } catch (e) {
    console.error("handler error", e);
    return json({ error: "server_error" }, 500, origin);
  }
});
