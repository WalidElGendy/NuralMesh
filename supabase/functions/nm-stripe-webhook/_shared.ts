// ============================================================
// Shared helpers for MeshNet money/edge functions.
// CORS, Supabase service client, Stripe REST, auth, config.
// ============================================================
import { createClient, type SupabaseClient } from "jsr:@supabase/supabase-js@2";

const ALLOWED = new Set([
  "https://dashboard.meshnet.co",
  "https://beta.meshnet.co",
  "https://meshnet.co",
  "https://www.meshnet.co",
  "http://localhost:8799",
]);

export function cors(origin: string | null): Record<string, string> {
  const o = origin && ALLOWED.has(origin) ? origin : "https://dashboard.meshnet.co";
  return {
    "Access-Control-Allow-Origin": o,
    "Access-Control-Allow-Headers":
      "authorization, x-admin-key, x-node-id, x-node-secret, content-type, stripe-signature, apikey",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Vary": "Origin",
  };
}

export function json(body: unknown, status = 200, origin: string | null = null): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...cors(origin), "content-type": "application/json" },
  });
}

export function preflight(req: Request): Response | null {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: cors(req.headers.get("origin")) });
  }
  return null;
}

export function admin(): SupabaseClient {
  return createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
    { auth: { persistSession: false } },
  );
}

export async function sha256hex(s: string): Promise<string> {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("");
}

// Verify a Supabase user JWT and return the auth user (or null).
export async function getUser(
  sb: SupabaseClient,
  authHeader: string | null,
): Promise<{ id: string; email: string | null } | null> {
  if (!authHeader) return null;
  const token = authHeader.replace(/^Bearer\s+/i, "");
  try {
    const { data, error } = await sb.auth.getUser(token);
    if (error || !data?.user) return null;
    return { id: data.user.id, email: data.user.email ?? null };
  } catch {
    return null;
  }
}

// Verify provider node credentials against providers.node_secret_hash.
export async function verifyNode(
  sb: SupabaseClient,
  nodeId: string | null | undefined,
  nodeSecret: string | null | undefined,
): Promise<Record<string, unknown> | null> {
  if (!nodeId || !nodeSecret) return null;
  const h = await sha256hex(nodeSecret);
  const { data } = await sb.from("providers").select("*").eq("node_id", nodeId).maybeSingle();
  if (!data || (data as Record<string, unknown>).node_secret_hash !== h) return null;
  return data as Record<string, unknown>;
}

// Admin gate: X-Admin-Key (ADMIN_API_KEY) OR allow-listed JWT email.
export async function isAdmin(sb: SupabaseClient, req: Request): Promise<boolean> {
  const key = req.headers.get("x-admin-key");
  const expected = Deno.env.get("ADMIN_API_KEY");
  if (expected && key && key === expected) return true;
  const user = await getUser(sb, req.headers.get("authorization"));
  const allow = (Deno.env.get("ADMIN_EMAILS") || "walidn20@gmail.com")
    .split(",").map((s) => s.trim().toLowerCase());
  if (user?.email && allow.includes(user.email.toLowerCase())) return true;
  return false;
}

export type Config = {
  rate: number; share: number; take: number; minUsd: number; currency: string;
};
export async function getConfig(sb: SupabaseClient): Promise<Config> {
  const { data } = await sb.from("app_config").select("key,value");
  const m: Record<string, unknown> = {};
  (data || []).forEach((r: { key: string; value: unknown }) => (m[r.key] = r.value));
  return {
    rate: Number(m["provider_payout_per_mtok_usd"] ?? 0.6),
    share: Number(m["provider_revenue_share"] ?? 0.7),
    take: Number(m["meshnet_take_rate"] ?? 0.3),
    minUsd: Number(m["payout_min_usd"] ?? 10),
    currency: String(m["payout_currency"] ?? "usd"),
  };
}

// ---- Stripe REST (form-encoded) via fetch; no SDK needed in Deno ----
export function stripeKey(): string {
  return Deno.env.get("STRIPE_SECRET_KEY") || "";
}
export async function stripe(
  path: string,
  method = "POST",
  form?: Record<string, string>,
): Promise<{ ok: boolean; status: number; data: any }> {
  const body = form ? new URLSearchParams(form).toString() : undefined;
  const r = await fetch("https://api.stripe.com/v1/" + path, {
    method,
    headers: {
      "Authorization": "Bearer " + stripeKey(),
      "Content-Type": "application/x-www-form-urlencoded",
      "Stripe-Version": "2024-06-20",
    },
    body,
  });
  const data = await r.json().catch(() => ({}));
  return { ok: r.ok, status: r.status, data };
}

// Verify a Stripe webhook signature (t + v1 HMAC-SHA256).
export async function verifyStripeSig(
  payload: string,
  sigHeader: string | null,
  secret: string,
): Promise<boolean> {
  if (!sigHeader || !secret) return false;
  const parts = Object.fromEntries(
    sigHeader.split(",").map((kv) => kv.split("=").map((s) => s.trim())),
  );
  const t = parts["t"]; const v1 = parts["v1"];
  if (!t || !v1) return false;
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`${t}.${payload}`));
  const expected = [...new Uint8Array(mac)].map((x) => x.toString(16).padStart(2, "0")).join("");
  // constant-time-ish compare
  if (expected.length !== v1.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) diff |= expected.charCodeAt(i) ^ v1.charCodeAt(i);
  return diff === 0;
}

export const monthStartISO = (): string => {
  const d = new Date();
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1)).toISOString();
};
