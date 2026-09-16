// nm-provider: GPU provider wallet, Stripe Connect (bank) onboarding, withdrawals.
// Auth: X-Node-Id + X-Node-Secret (or in JSON body) verified against providers.node_secret_hash.
import {
  admin, preflight, json, verifyNode, getConfig, stripe,
} from "./_shared.ts";

function walletMath(provider: any, payouts: any[], rate: number) {
  const lifetime = (Number(provider.total_tokens_served || 0) * rate) / 1e6;
  let paid = 0, pending = 0;
  for (const p of payouts) {
    const amt = Number(p.usd_equivalent || 0);
    if (p.status === "paid") paid += amt;
    else if (["requested", "approved", "processing"].includes(p.status)) pending += amt;
  }
  const available = Math.max(0, lifetime - paid - pending);
  return { lifetime, paid, pending, available };
}

Deno.serve(async (req) => {
  const pf = preflight(req); if (pf) return pf;
  const origin = req.headers.get("origin");
  const sb = admin();

  const body: Record<string, any> = req.method === "POST" ? await req.json().catch(() => ({})) : {};
  const nodeId = req.headers.get("x-node-id") || body.node_id;
  const nodeSecret = req.headers.get("x-node-secret") || body.node_secret;
  const action = body.action || new URL(req.url).searchParams.get("action") || "wallet";

  const provider = await verifyNode(sb, nodeId, nodeSecret);
  if (!provider) return json({ error: "invalid_node_credentials" }, 401, origin);

  const cfg = await getConfig(sb);

  try {
    const { data: payouts } = await sb.from("provider_payouts")
      .select("*").eq("provider_id", provider.id).order("created_at", { ascending: false });
    const w = walletMath(provider, payouts || [], cfg.rate);

    if (action === "connect") {
      // Create or reuse a Stripe Connect Express account, return onboarding link.
      let acct = provider.stripe_connect_account_id as string | undefined;
      if (!acct) {
        const country = String(body.country || "US").toUpperCase();
        const c = await stripe("accounts", "POST", {
          "type": "express",
          "email": String(provider.email || ""),
          "country": country,
          "business_type": "individual",
          "capabilities[transfers][requested]": "true",
          "metadata[provider_id]": String(provider.id),
          "metadata[node_id]": String(provider.node_id),
        });
        if (!c.ok) return json({ error: "connect_account_failed", detail: c.data?.error?.message }, 502, origin);
        acct = c.data.id;
        await sb.from("providers").update({
          stripe_connect_account_id: acct, connect_status: "onboarding",
        }).eq("id", provider.id);
      }
      const ret = String(body.return_url || "https://dashboard.meshnet.co/provider.html");
      const link = await stripe("account_links", "POST", {
        "account": acct!,
        "type": "account_onboarding",
        "refresh_url": ret + "?connect=refresh",
        "return_url": ret + "?connect=done",
      });
      if (!link.ok) return json({ error: "connect_link_failed", detail: link.data?.error?.message }, 502, origin);
      return json({ url: link.data.url, account_id: acct, status: provider.connect_status || "onboarding" }, 200, origin);
    }

    if (action === "withdraw") {
      const amount = Math.round(Number(body.amount_usd || 0) * 100) / 100;
      if (!(amount > 0)) return json({ error: "invalid_amount" }, 400, origin);
      if (!provider.stripe_connect_account_id || !provider.payouts_enabled) {
        return json({ error: "connect_required", message: "Connect a bank account first." }, 400, origin);
      }
      if (amount < cfg.minUsd) {
        return json({ error: "below_minimum", min_usd: cfg.minUsd }, 400, origin);
      }
      if (amount > w.available + 1e-9) {
        return json({ error: "insufficient_balance", available_usd: w.available }, 400, origin);
      }
      const period = new Date().toISOString().slice(0, 7); // YYYY-MM
      const rec = {
        id: crypto.randomUUID(),
        provider_id: provider.id,
        period,
        credits: 0,
        usd_equivalent: amount,
        tokens_settled: Math.round((amount / cfg.rate) * 1e6),
        payout_method: { type: "stripe_connect", account_id: provider.stripe_connect_account_id },
        status: "requested",
        note: String(body.note || ""),
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      const { error } = await sb.from("provider_payouts").insert(rec);
      if (error) return json({ error: "insert_failed", detail: error.message }, 500, origin);
      return json({ ok: true, payout: rec, message: "Withdrawal requested. It will be reviewed and paid to your bank." }, 200, origin);
    }

    // default: wallet summary
    const perMonth = (Number(provider.tokens_month || 0) * cfg.rate) / 1e6;
    const perToday = (Number(provider.tokens_today || 0) * cfg.rate) / 1e6;
    return json({
      provider: { id: provider.id, email: provider.email, node_id: provider.node_id, status: provider.status },
      rate_per_mtok_usd: cfg.rate,
      payout_min_usd: cfg.minUsd,
      total_tokens_served: Number(provider.total_tokens_served || 0),
      tokens_today: Number(provider.tokens_today || 0),
      tokens_month: Number(provider.tokens_month || 0),
      earnings_today_usd: perToday,
      earnings_month_usd: perMonth,
      wallet: {
        lifetime_earned_usd: w.lifetime,
        paid_usd: w.paid,
        pending_usd: w.pending,
        available_usd: w.available,
      },
      connect: {
        account_id: provider.stripe_connect_account_id || null,
        status: provider.connect_status || "none",
        onboarded: !!provider.connect_onboarded,
        payouts_enabled: !!provider.payouts_enabled,
      },
      payouts: (payouts || []).map((p: any) => ({
        id: p.id, period: p.period, usd: Number(p.usd_equivalent || 0),
        status: p.status, created_at: p.created_at, paid_at: p.paid_at,
        stripe_transfer_id: p.stripe_transfer_id,
      })),
    }, 200, origin);
  } catch (e) {
    return json({ error: "server_error", detail: String((e as Error).message) }, 500, origin);
  }
});
