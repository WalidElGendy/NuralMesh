import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string;
const anon = import.meta.env.VITE_SUPABASE_ANON_KEY as string;

if (!url || !anon) {
  // Fail loudly in dev rather than silently rendering an empty map.
  console.error(
    "[EF] Missing VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY. Copy .env.example → .env.local",
  );
}

export const supabase = createClient(url, anon, {
  auth: { persistSession: true, autoRefreshToken: true },
  // The EF domain lives in its own schema, isolated from MeshNet's public tables.
  db: { schema: "ef" },
});

/** A client pinned to the public schema, for MeshNet-level reads (plans, etc.). */
export const supabasePublic = createClient(url, anon, {
  auth: { persistSession: true, autoRefreshToken: true },
});

export async function getAccessToken(): Promise<string | null> {
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}
