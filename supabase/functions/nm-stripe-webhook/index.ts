// nm-stripe-webhook: Stripe events -> subscription state + Connect onboarding state.
// Auth: Stripe-Signature (HMAC) verified with STRIPE_WEBHOOK_SECRET. verify_jwt=false.
import { admin, json, verifyStripeSig } from "./_shared.ts";

Deno.serve(async (req) => {
  if (req.method !== "POST") return new Response("method", { status: 405 });
  const sb = admin();
  const raw = await req.text();
  const secret = Deno.env.get("STRIPE_WEBHOOK_SECRET") || "";
  const ok = await verifyStripeSig(raw, req.headers.get("stripe-signature"), secret);
  if (!ok) return json({ error: "bad_signature" }, 400);

  let evt: any;
  try { evt = JSON.parse(raw); } catch { return json({ error: "bad_json" }, 400); }
  const obj = evt?.data?.object || {};

  try {
    switch (evt.type) {
      case "checkout.session.completed": {
        const userId = obj.metadata?.user_id;
        const tier = obj.metadata?.tier;
        if (userId) {
          await sb.from("billing").upsert({
            user_id: userId,
            plan_id: tier || "pro",
            stripe_customer_id: obj.customer,
            stripe_subscription_id: obj.subscription,
          }, { onConflict: "user_id" });
          await sb.from("users").update({ subscription_status: "active", stripe_customer_id: obj.customer }).eq("id", userId);
        }
        break;
      }
      case "customer.subscription.created":
      case "customer.subscription.updated": {
        const userId = obj.metadata?.user_id;
        const tier = obj.metadata?.tier;
        const status = obj.status; // active, past_due, canceled, etc.
        const patch: Record<string, unknown> = { stripe_subscription_id: obj.id };
        if (tier) patch.plan_id = tier;
        if (userId) {
          await sb.from("billing").upsert({ user_id: userId, ...patch }, { onConflict: "user_id" });
          await sb.from("users").update({ subscription_status: status }).eq("id", userId);
        } else if (obj.customer) {
          await sb.from("billing").update(patch).eq("stripe_customer_id", obj.customer);
        }
        break;
      }
      case "customer.subscription.deleted": {
        const userId = obj.metadata?.user_id;
        if (userId) {
          await sb.from("billing").update({ plan_id: "free", stripe_subscription_id: null }).eq("user_id", userId);
          await sb.from("users").update({ subscription_status: "canceled" }).eq("id", userId);
        } else if (obj.customer) {
          await sb.from("billing").update({ plan_id: "free", stripe_subscription_id: null }).eq("stripe_customer_id", obj.customer);
        }
        break;
      }
      case "account.updated": {
        // Stripe Connect (provider bank) onboarding progress.
        const acct = obj.id;
        const payoutsEnabled = !!obj.payouts_enabled;
        const detailsSubmitted = !!obj.details_submitted;
        const status = payoutsEnabled ? "active" : (detailsSubmitted ? "restricted" : "onboarding");
        await sb.from("providers").update({
          connect_onboarded: detailsSubmitted,
          payouts_enabled: payoutsEnabled,
          connect_status: status,
        }).eq("stripe_connect_account_id", acct);
        break;
      }
      default:
        break;
    }
  } catch (e) {
    console.error("webhook_handler_error", evt?.type, String((e as Error).message));
    return json({ received: true, warning: "handler_error" }, 200);
  }
  return json({ received: true }, 200);
});
