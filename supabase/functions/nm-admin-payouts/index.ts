// nm-admin-payouts: admin review/approve provider withdrawals (real Stripe Transfer),
// plus subscription revenue summary (the financial-model surface).
// Auth: X-Admin-Key OR allow-listed Supabase JWT email.
import { admin, preflight, json, isAdmin, getConfig, stripe } from "./_shared.ts";

Deno.serve(async (req) => {
  const pf = preflight(req); if (pf) return pf;
  const origin = req.headers.get("origin");
  const sb = admin();

  if (!(await isAdmin(sb, req))) return json({ error: "admin_required" }, 403, origin);

  const url = new URL(req.url);
  let action = url.searchParams.get("action") || "list";
  let body: Record<string, any> = {};
  if (req.method === "POST") { body = await req.json().catch(() => ({})); action = body.action || action; }

  const cfg = await getConfig(sb);

  try {
    if (action === "revenue") {
      // Subscription revenue engine: MRR, 70/30 split, by tier.
      const { data: subs } = await sb.from("billing")
        .select("user_id,plan_id,stripe_subscription_id")
        .not("stripe_subscription_id", "is", null);
      const { data: plans } = await sb.from("plans").select("id,name,price_monthly");
      const priceOf: Record<string, number> = {};
      const nameOf: Record<string, string> = {};
      (plans || []).forEach((p: any) => { priceOf[p.id] = Number(p.price_monthly); nameOf[p.id] = p.name; });
      let mrr = 0; const byTier: Record<string, { name: string; count: number; mrr: number }> = {};
      for (const s of subs || []) {
        const price = priceOf[s.plan_id] || 0; mrr += price;
        const t = byTier[s.plan_id] || (byTier[s.plan_id] = { name: nameOf[s.plan_id] || s.plan_id, count: 0, mrr: 0 });
        t.count += 1; t.mrr += price;
      }
      return json({
        subscribers: (subs || []).length,
        mrr, arr: mrr * 12,
        provider_pool: mrr * cfg.share,
        meshnet_revenue: mrr * cfg.take,
        provider_share: cfg.share, meshnet_take: cfg.take,
        by_tier: byTier,
      }, 200, origin);
    }

    if (action === "approve") {
      const payoutId = String(body.payout_id || "");
      const { data: p } = await sb.from("provider_payouts").select("*").eq("id", payoutId).maybeSingle();
      if (!p) return json({ error: "not_found" }, 404, origin);
      if (!["requested", "approved"].includes(p.status)) {
        return json({ error: "invalid_state", status: p.status }, 409, origin);
      }
      const { data: provider } = await sb.from("providers").select("*").eq("id", p.provider_id).maybeSingle();
      const acct = provider?.stripe_connect_account_id;
      if (!acct) return json({ error: "provider_not_connected" }, 400, origin);

      const amountCents = Math.round(Number(p.usd_equivalent) * 100);
      const tr = await stripe("transfers", "POST", {
        "amount": String(amountCents),
        "currency": cfg.currency,
        "destination": acct,
        "description": `MeshNet GPU provider payout ${p.provider_id}`,
        "metadata[payout_id]": payoutId,
        "metadata[provider_id]": String(p.provider_id),
      });
      if (!tr.ok) {
        await sb.from("provider_payouts").update({ status: "failed", note: tr.data?.error?.message, updated_at: new Date().toISOString() }).eq("id", payoutId);
        return json({ error: "transfer_failed", detail: tr.data?.error?.message }, 502, origin);
      }
      await sb.from("provider_payouts").update({
        status: "paid", stripe_transfer_id: tr.data.id,
        paid_at: new Date().toISOString(), updated_at: new Date().toISOString(),
        note: String(body.note || p.note || ""),
      }).eq("id", payoutId);
      return json({ ok: true, payout_id: payoutId, stripe_transfer_id: tr.data.id, amount_usd: Number(p.usd_equivalent) }, 200, origin);
    }

    if (action === "reject") {
      const payoutId = String(body.payout_id || "");
      const { error } = await sb.from("provider_payouts").update({
        status: "rejected", note: String(body.note || "rejected by admin"), updated_at: new Date().toISOString(),
      }).eq("id", payoutId).eq("status", "requested");
      if (error) return json({ error: "reject_failed", detail: error.message }, 500, origin);
      return json({ ok: true, payout_id: payoutId }, 200, origin);
    }

    // default: list pending payouts (+ recent history)
    const { data: pending } = await sb.from("provider_payouts")
      .select("*").in("status", ["requested", "approved"]).order("created_at", { ascending: true });
    const { data: recent } = await sb.from("provider_payouts")
      .select("*").in("status", ["paid", "rejected", "failed"]).order("paid_at", { ascending: false }).limit(25);

    // hydrate provider info
    const ids = [...new Set([...(pending || []), ...(recent || [])].map((p: any) => p.provider_id))];
    const provMap: Record<string, any> = {};
    if (ids.length) {
      const { data: provs } = await sb.from("providers")
        .select("id,email,node_id,stripe_connect_account_id,payouts_enabled,connect_status").in("id", ids);
      (provs || []).forEach((pr: any) => provMap[pr.id] = pr);
    }
    const shape = (p: any) => ({
      id: p.id, provider_id: p.provider_id,
      provider_email: provMap[p.provider_id]?.email || null,
      node_id: provMap[p.provider_id]?.node_id || null,
      connected: !!provMap[p.provider_id]?.stripe_connect_account_id,
      payouts_enabled: !!provMap[p.provider_id]?.payouts_enabled,
      usd: Number(p.usd_equivalent || 0), status: p.status,
      created_at: p.created_at, paid_at: p.paid_at,
      stripe_transfer_id: p.stripe_transfer_id, note: p.note,
    });
    return json({
      pending: (pending || []).map(shape),
      recent: (recent || []).map(shape),
      pending_total_usd: (pending || []).reduce((a: number, p: any) => a + Number(p.usd_equivalent || 0), 0),
    }, 200, origin);
  } catch (e) {
    return json({ error: "server_error", detail: String((e as Error).message) }, 500, origin);
  }
});
