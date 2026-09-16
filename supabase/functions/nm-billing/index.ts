// nm-billing: user-facing token usage + Stripe subscription checkout.
// Auth: Supabase user JWT (Authorization: Bearer). verify_jwt=false (we verify inside so OPTIONS works).
import {
  admin, cors, preflight, json, getUser, getConfig, stripe, monthStartISO,
} from "./_shared.ts";

Deno.serve(async (req) => {
  const pf = preflight(req); if (pf) return pf;
  const origin = req.headers.get("origin");
  const sb = admin();

  const user = await getUser(sb, req.headers.get("authorization"));
  if (!user) return json({ error: "unauthorized" }, 401, origin);

  const url = new URL(req.url);
  let action = url.searchParams.get("action") || "";
  let body: Record<string, unknown> = {};
  if (req.method === "POST") {
    body = await req.json().catch(() => ({}));
    action = (body.action as string) || action;
  }

  try {
    if (action === "plans") {
      const { data } = await sb.from("plans")
        .select("id,name,price_monthly,token_allowance_mtok,price_per_mtok")
        .gt("price_monthly", 0).order("price_monthly");
      return json({ plans: data || [] }, 200, origin);
    }

    if (action === "checkout") {
      const tier = String(body.tier || "");
      const { data: plan } = await sb.from("plans").select("*").eq("id", tier).maybeSingle();
      if (!plan || Number(plan.price_monthly) <= 0) {
        return json({ error: "invalid_tier" }, 400, origin);
      }
      if (!stripe) { /* noop */ }
      // ensure a Stripe customer
      const { data: billing } = await sb.from("billing").select("*").eq("user_id", user.id).maybeSingle();
      let customer = billing?.stripe_customer_id as string | undefined;
      if (!customer) {
        const c = await stripe("customers", "POST", {
          email: user.email || "",
          "metadata[user_id]": user.id,
        });
        if (!c.ok) return json({ error: "stripe_customer_failed", detail: c.data?.error?.message }, 502, origin);
        customer = c.data.id;
        await sb.from("billing").upsert({ user_id: user.id, plan_id: billing?.plan_id || "free", stripe_customer_id: customer }, { onConflict: "user_id" });
        await sb.from("users").update({ stripe_customer_id: customer }).eq("id", user.id);
      }
      const ret = String(body.return_url || "https://dashboard.meshnet.co/account.html");
      const amount = Math.round(Number(plan.price_monthly) * 100);
      const form: Record<string, string> = {
        "mode": "subscription",
        "customer": customer!,
        "success_url": ret + "?checkout=success",
        "cancel_url": ret + "?checkout=cancel",
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "usd",
        "line_items[0][price_data][unit_amount]": String(amount),
        "line_items[0][price_data][recurring][interval]": "month",
        "line_items[0][price_data][product_data][name]": `MeshNet ${plan.name}`,
        "line_items[0][price_data][product_data][metadata][tier]": tier,
        "allow_promotion_codes": "true",
        "metadata[user_id]": user.id,
        "metadata[tier]": tier,
        "subscription_data[metadata][user_id]": user.id,
        "subscription_data[metadata][tier]": tier,
      };
      const s = await stripe("checkout/sessions", "POST", form);
      if (!s.ok) return json({ error: "stripe_checkout_failed", detail: s.data?.error?.message }, 502, origin);
      return json({ url: s.data.url }, 200, origin);
    }

    // default: usage summary
    const cfg = await getConfig(sb);
    const { data: billing } = await sb.from("billing").select("*").eq("user_id", user.id).maybeSingle();
    const planId = billing?.plan_id || "free";
    const { data: plan } = await sb.from("plans").select("*").eq("id", planId).maybeSingle();
    const allowance = Number(plan?.token_allowance_mtok || 0) * 1e6;

    // tokens used this month + 14-day history from routing_events (canonical per-request log)
    const since = monthStartISO();
    const { data: evs } = await sb.from("routing_events")
      .select("tokens,created_at").eq("user_id", user.id).gte("created_at", since);
    let used = 0;
    for (const e of evs || []) used += Number(e.tokens || 0);

    const d14 = new Date(Date.now() - 14 * 864e5).toISOString();
    const { data: hev } = await sb.from("routing_events")
      .select("tokens,created_at").eq("user_id", user.id).gte("created_at", d14);
    const buckets: Record<string, number> = {};
    for (const e of hev || []) {
      const day = String(e.created_at).slice(0, 10);
      buckets[day] = (buckets[day] || 0) + Number(e.tokens || 0);
    }
    const history = Object.entries(buckets).map(([day, tokens]) => ({ day, tokens })).sort((a, b) => a.day.localeCompare(b.day));

    const price = Number(plan?.price_monthly || 0);
    const remaining = Math.max(0, allowance - used);
    return json({
      user: { id: user.id, email: user.email },
      tier: planId,
      plan_name: plan?.name || "Free",
      price_monthly: price,
      subscription_status: billing?.stripe_subscription_id ? "active" : (billing ? "incomplete" : "none"),
      allowance_tokens: allowance,
      allowance_mtok: Number(plan?.token_allowance_mtok || 0),
      tokens_used: used,
      tokens_remaining: remaining,
      pct_used: allowance > 0 ? Math.min(100, (used / allowance) * 100) : 0,
      effective_price_per_mtok: Number(plan?.price_per_mtok || 0),
      // "value": what those tokens would cost at GPT-4o blended ($4.75/1M)
      value_at_gpt4o_usd: (used / 1e6) * 4.75,
      history,
      period_start: since,
    }, 200, origin);
  } catch (e) {
    return json({ error: "server_error", detail: String((e as Error).message) }, 500, origin);
  }
});
