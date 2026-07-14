/**
 * Invitation gate client.
 *
 * Talks to the `ef-invite` edge function, which is the only thing permitted to read
 * MeshNet's `invites` table. The browser never sees it: if the anon key could read
 * `public.invites`, the valid codes would just be listable.
 */

import { getAccessToken, supabase } from "./supabase";

const FN_BASE = `${import.meta.env.VITE_SUPABASE_URL}/functions/v1/ef-invite`;
const ANON = import.meta.env.VITE_SUPABASE_ANON_KEY as string;

export interface InviteResult {
  valid: boolean;
  reason?: string;
  used?: boolean;
}

async function call(body: Record<string, unknown>, token?: string): Promise<InviteResult> {
  try {
    const res = await fetch(FN_BASE, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        // The function is public (it must be callable before sign-in), so the anon key is
        // just the gateway credential. The real check happens server-side.
        Authorization: `Bearer ${token ?? ANON}`,
        apikey: ANON,
      },
      body: JSON.stringify(body),
    });
    return (await res.json()) as InviteResult;
  } catch {
    return { valid: false, reason: "Could not reach the invitation service. Try again." };
  }
}

/** Check an (email, code) pair. Does NOT consume the invite. */
export function verifyInvite(email: string, code: string): Promise<InviteResult> {
  return call({ action: "verify", email, code });
}

/** Consume the invite. Only meaningful once a real session exists. */
export async function claimInvite(email: string, code: string): Promise<InviteResult> {
  const token = await getAccessToken();
  if (!token) return { valid: false, reason: "Not signed in." };
  return call({ action: "claim", email, code }, token);
}

/** Exposed for the sign-out path in the shell. */
export { supabase };
