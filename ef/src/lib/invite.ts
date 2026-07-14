/**
 * Invitation gate client.
 *
 * Talks to the `ef-invite` edge function, which is the only thing permitted to read
 * MeshNet's `invites` table or `auth.users`. The browser never sees either: if the anon key
 * could read `public.invites`, the valid codes would simply be listable.
 */

import { getAccessToken } from "./supabase";

const FN = `${import.meta.env.VITE_SUPABASE_URL}/functions/v1/ef-invite`;
const ANON = import.meta.env.VITE_SUPABASE_ANON_KEY as string;

export interface InviteResult {
  valid: boolean;
  reason?: string;
  /** The code was already redeemed. */
  used?: boolean;
  /** An auth account already exists for this email. */
  hasAccount?: boolean;
  /** The person still has to SET a password (new account, or a targeted invite authorising
   *  a reset). When false, they already have one and should just sign in. */
  needsPassword?: boolean;
  /** The password was set on a pre-existing account. */
  reset?: boolean;
  /** A fresh account was just created. */
  created?: boolean;
  /** The EF role the invite carries. */
  role?: "viewer" | "analyst" | "operator" | "admin";
}

async function call(body: Record<string, unknown>, token?: string): Promise<InviteResult> {
  try {
    const res = await fetch(FN, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        // The function must be callable before sign-in, so the anon key is just the gateway
        // credential. Every real check happens server-side under the service role.
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

/** Check an (email, code) pair. Never consumes the invite. */
export function verifyInvite(email: string, code: string): Promise<InviteResult> {
  return call({ action: "verify", email, code });
}

/** First run: create the account, grant the membership, burn the invite. */
export function setPassword(
  email: string,
  code: string,
  password: string,
): Promise<InviteResult> {
  return call({ action: "set_password", email, code, password });
}

/** Returning user: attach membership and consume the invite. Requires a live session. */
export async function claimInvite(email: string, code: string): Promise<InviteResult> {
  const token = await getAccessToken();
  if (!token) return { valid: false, reason: "Not signed in." };
  return call({ action: "claim", email, code }, token);
}
