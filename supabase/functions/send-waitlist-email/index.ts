// Sends the MeshNet beta welcome email (activation code + signup link) when a
// row is inserted into public.waitlist_users (AI users) or
// public.waitlist_providers (GPU providers). Called by a Database Webhook on
// each table; the webhook body carries { table, record }.
const BETA = "https://beta.meshnet.co";

const esc = (s: unknown) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));

function codeBox(code: string) {
  return '<p style="font-size:20px;font-weight:bold;letter-spacing:2px;background:#f4f4f5;' +
    'padding:12px 16px;border-radius:8px;display:inline-block">' + esc(code) + "</p>";
}

function userEmail(name: string, code: string, url: string) {
  const hi = name ? "Hi " + esc(name) + "," : "Hi,";
  return {
    subject: "Welcome to the MeshNet AI beta",
    html:
      '<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;color:#111">' +
      "<h2>Welcome to the MeshNet AI beta</h2><p>" + hi + "</p>" +
      "<p>You now have early access to cheap, verified AI inference on MeshNet.</p>" +
      "<p><strong>Your activation code:</strong></p>" + codeBox(code) +
      "<h3>Getting started</h3><ol>" +
      '<li>Create your account here: <a href="' + url + '">' + url + "</a></li>" +
      "<li>Sign up with this same email address and enter the activation code above when prompted.</li>" +
      "<li>You can start sending jobs right away: the network routes each job to the best available GPU, verified on-chain.</li>" +
      "</ol>" +
      '<p style="color:#666;font-size:12px">If you didn\'t request this, ignore this email.</p></div>',
    text:
      hi + "\n\nYou now have early access to cheap, verified AI inference on MeshNet.\n\n" +
      "Your activation code: " + code + "\n\n" +
      "1. Create your account here: " + url + "\n" +
      "2. Sign up with this same email address and enter the activation code when prompted.\n" +
      "3. You can start sending jobs right away.\n\n" +
      "If you didn't request this, ignore this email.",
  };
}

function providerEmail(name: string, code: string, url: string) {
  const hi = name ? "Hi " + esc(name) + "," : "Hi,";
  const setup = BETA + "/host/setup.html";
  return {
    subject: "Your MeshNet GPU provider access",
    html:
      '<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;color:#111">' +
      "<h2>Welcome to the MeshNet GPU provider beta</h2><p>" + hi + "</p>" +
      "<p>You're in. Your GPU can now start earning on the MeshNet network.</p>" +
      "<p><strong>Your activation code:</strong></p>" + codeBox(code) +
      "<h3>How to activate your node</h3><ol>" +
      '<li>Create your provider account: <a href="' + url + '">' + url + "</a></li>" +
      "<li>Sign up with this same email address and enter the activation code above when prompted.</li>" +
      '<li>Download and run the node installer for your machine: <a href="' + setup + '">' + setup + "</a></li>" +
      "<li>Your node registers itself and shows as <strong>online</strong> once it sends its first heartbeat.</li>" +
      "</ol>" +
      "<p>Once online, jobs route to your GPU automatically and your earnings build up in your host dashboard.</p>" +
      '<p style="color:#666;font-size:12px">If you didn\'t request this, ignore this email.</p></div>',
    text:
      hi + "\n\nYou're in. Your GPU can now start earning on the MeshNet network.\n\n" +
      "Your activation code: " + code + "\n\n" +
      "1. Create your provider account: " + url + "\n" +
      "2. Sign up with this same email address and enter the activation code when prompted.\n" +
      "3. Download and run the node installer: " + setup + "\n" +
      "4. Your node shows as online once it sends its first heartbeat.\n\n" +
      "If you didn't request this, ignore this email.",
  };
}

Deno.serve(async (req) => {
  try {
    const body = await req.json();
    const row = body.record ?? body;
    const intent = (body.table === "waitlist_providers" || body.kind === "provider") ? "provider" : "user";
    const email = String(row.email ?? "").trim();
    const fullName = String(row.full_name ?? "").trim().split("\n")[0].slice(0, 80);
    if (!email) {
      return new Response(JSON.stringify({ error: "no email in payload" }), { status: 400 });
    }

    const RESEND_API_KEY = Deno.env.get("RESEND_API_KEY");
    const FROM = Deno.env.get("WAITLIST_FROM_EMAIL") ?? "MeshNet <beta@meshnet.co>";
    if (!RESEND_API_KEY) {
      return new Response(JSON.stringify({ error: "RESEND_API_KEY not set" }), { status: 500 });
    }

    const SUPABASE_URL = Deno.env.get("SUPABASE_URL");
    let SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
    if (!SERVICE_KEY) {
      try {
        const secretKeys = JSON.parse(Deno.env.get("SUPABASE_SECRET_KEYS") ?? "{}");
        SERVICE_KEY = secretKeys.service_role ?? secretKeys.secret ?? Object.values(secretKeys)[0];
      } catch (_) { /* ignore */ }
    }
    if (!SUPABASE_URL || !SERVICE_KEY) {
      return new Response(JSON.stringify({ error: "supabase service credentials unavailable" }), { status: 500 });
    }
    const dbHeaders = {
      "apikey": SERVICE_KEY,
      "Authorization": "Bearer " + SERVICE_KEY,
      "Content-Type": "application/json",
    };

    // 1) Reuse a code already issued to this email for this intent (retries).
    let code: string | null = null;
    const existingRes = await fetch(
      SUPABASE_URL + "/rest/v1/invites?select=code&email=eq." + encodeURIComponent(email) +
        "&intent=eq." + intent + "&revoked=eq.false&claimed_at=is.null&limit=1",
      { headers: dbHeaders },
    );
    const existing = await existingRes.json();
    if (Array.isArray(existing) && existing.length > 0) code = existing[0].code;

    // 2) Otherwise claim one free code atomically (the RPC tags it 'user').
    if (!code) {
      const rpcRes = await fetch(SUPABASE_URL + "/rest/v1/rpc/claim_invite_for_email", {
        method: "POST",
        headers: dbHeaders,
        body: JSON.stringify({ p_email: email }),
      });
      const rpcOut = await rpcRes.json();
      code = (typeof rpcOut === "string") ? rpcOut : (rpcOut && rpcOut.claim_invite_for_email) || null;
      if (!code) {
        console.error("No available invite codes to assign", rpcOut);
        return new Response(JSON.stringify({ error: "no available invite codes" }), { status: 409 });
      }
      // Signup checks the code's intent, so a provider's code must say so.
      if (intent === "provider") {
        await fetch(SUPABASE_URL + "/rest/v1/invites?code=eq." + encodeURIComponent(code), {
          method: "PATCH",
          headers: { ...dbHeaders, "Prefer": "return=minimal" },
          body: JSON.stringify({ intent: "provider", notes: "Auto-issued via waitlist (provider)" }),
        });
      }
    }

    const signupUrl = BETA + "/signup.html?intent=" + intent + "&invite=" + encodeURIComponent(code);
    const msg = intent === "provider" ? providerEmail(fullName, code, signupUrl) : userEmail(fullName, code, signupUrl);

    const res = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: { "Authorization": "Bearer " + RESEND_API_KEY, "Content-Type": "application/json" },
      body: JSON.stringify({ from: FROM, to: [email], subject: msg.subject, html: msg.html, text: msg.text }),
    });
    const result = await res.json();
    if (!res.ok) {
      console.error("Resend error", intent, result);
      return new Response(JSON.stringify({ error: "resend failed", detail: result }), { status: 502 });
    }
    console.info("Sent welcome", intent, "id", result.id);
    return new Response(JSON.stringify({ ok: true, intent, id: result.id }), { status: 200 });
  } catch (e) {
    console.error("handler error", e);
    return new Response(JSON.stringify({ error: String(e) }), { status: 500 });
  }
});
