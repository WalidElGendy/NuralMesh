import { useState } from "react";
import { ArrowRight, ShieldCheck } from "lucide-react";

import { supabase } from "../lib/supabase";
import { claimInvite, setPassword, verifyInvite } from "../lib/invite";
import { SOVEREIGN_INFERENCE } from "../lib/mesh";

/**
 * The gate.
 *
 *   invite  → check (email, code). The server also tells us whether an account exists.
 *   create  → first run: choose a password. The server makes the account, grants the EF
 *             membership the invite carries, and burns the code.
 *   signin  → returning user: enter password.
 *
 * There is no confirmation email by design. The invite code is already the proof of
 * identity; a round-trip through an inbox adds no security and strands people who never
 * receive it.
 */
type Step = "invite" | "create" | "signin";

export default function Auth() {
  const [step, setStep] = useState<Step>("invite");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  /** True when we're setting a password on an account that already existed. */
  const [isReset, setIsReset] = useState(false);

  async function submitInvite(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);

    const res = await verifyInvite(email, code);
    setBusy(false);

    if (!res.valid) {
      setErr(res.reason ?? "That invitation code isn't valid for this email.");
      return;
    }
    // The server decides. It knows whether a password was ever set, and whether this invite
    // authorises setting one — guessing from hasAccount alone is what stranded people at a
    // password prompt for a password that never existed.
    setIsReset(!!res.hasAccount);
    setStep(res.needsPassword ? "create" : "signin");
  }

  async function submitCreate(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);

    if (password !== confirm) {
      setErr("Those passwords don't match.");
      return;
    }
    if (password.length < 10) {
      setErr("Choose a password of at least 10 characters.");
      return;
    }

    setBusy(true);
    const res = await setPassword(email, code, password);

    if (!res.valid) {
      setBusy(false);
      setErr(res.reason ?? "Could not create your account.");
      // Account already existed → send them to sign-in rather than a dead end.
      if (res.hasAccount) setStep("signin");
      return;
    }

    // The account exists now. Sign straight in — making them re-type it would be pointless.
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setBusy(false);
    if (error) {
      setErr(`Account created, but sign-in failed: ${error.message}`);
      setStep("signin");
    }
  }

  async function submitSignIn(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);

    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) {
      setBusy(false);
      setErr(error.message);
      return;
    }

    // Idempotent: attaches the membership if it's somehow missing, and burns the invite.
    await claimInvite(email, code);
    setBusy(false);
  }

  const back = () => {
    setStep("invite");
    setErr(null);
    setPw("");
    setConfirm("");
  };

  return (
    <div className="flex min-h-screen">
      <div className="flex w-full flex-col justify-between px-8 py-10 lg:w-[46%] lg:px-16">
        <div className="flex items-center gap-3">
          <img src="/logo.svg" alt="" className="h-10 w-10" />
          <div>
            <div className="font-display text-lg leading-none tracking-tight text-navy-900">
              EFund
            </div>
            <div dir="rtl" className="mt-1 text-xs leading-none text-navy-900/50">
              صندوق البيئة
            </div>
          </div>
        </div>

        <div className="mx-auto w-full max-w-sm animate-fade-up py-12">
          {/* ── Step 1 · invitation ─────────────────────────────────────────────── */}
          {step === "invite" && (
            <form onSubmit={submitInvite}>
              <h1 className="font-display text-[2.6rem] leading-[1.1] tracking-tight text-navy-900">
                Join the Saudi
                <br />
                Environment Fund.
              </h1>
              <p className="mt-4 text-sm leading-relaxed text-navy-900/55">
                Enter your email and invitation code to fund, track and verify sustainability
                initiatives across the Kingdom.
              </p>

              <label className="label mt-8 block">Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
                placeholder="name@ef.gov.sa"
                className="input mt-1.5"
              />

              <label className="label mt-4 block">Invitation code</label>
              <input
                value={code}
                onChange={(e) => setCode(e.target.value.toUpperCase())}
                required
                placeholder="EF-XXXX-XXXX"
                className="input mt-1.5 font-mono tracking-widest"
              />

              {err && <p className="mt-3 text-xs leading-relaxed text-clay">{err}</p>}

              <button
                type="submit"
                disabled={busy || !email.trim() || !code.trim()}
                className="btn-primary mt-5 w-full"
              >
                {busy ? "Checking…" : "Continue"}
                {!busy && <ArrowRight size={15} />}
              </button>
            </form>
          )}

          {/* ── Step 2a · first run, choose a password ──────────────────────────── */}
          {step === "create" && (
            <form onSubmit={submitCreate}>
              <button type="button" onClick={back} className="label mb-6 hover:text-navy-600">
                ← Back
              </button>

              <h1 className="font-display text-[2.6rem] leading-[1.1] tracking-tight text-navy-900">
                Set your
                <br />
                password.
              </h1>
              <p className="mt-3 text-sm leading-relaxed text-navy-900/55">
                Invitation accepted for{" "}
                <span className="font-medium text-navy-800">{email}</span>.{" "}
                {isReset
                  ? "You already have an account — choose a new password for it."
                  : "Choose a password to finish setting up your account."}{" "}
                There's no confirmation email to wait for.
              </p>

              <label className="label mt-8 block">New password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPw(e.target.value)}
                required
                autoFocus
                autoComplete="new-password"
                className="input mt-1.5"
              />
              <p className="mt-1.5 text-[11px] text-navy-900/40">At least 10 characters.</p>

              <label className="label mt-4 block">Confirm password</label>
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
                autoComplete="new-password"
                className="input mt-1.5"
              />

              {err && <p className="mt-3 text-xs leading-relaxed text-clay">{err}</p>}

              <button
                type="submit"
                disabled={busy || !password || !confirm}
                className="btn-primary mt-5 w-full"
              >
                {busy
                  ? isReset
                    ? "Saving…"
                    : "Creating your account…"
                  : isReset
                    ? "Set password and sign in"
                    : "Create account"}
                {!busy && <ArrowRight size={15} />}
              </button>
            </form>
          )}

          {/* ── Step 2b · returning user ────────────────────────────────────────── */}
          {step === "signin" && (
            <form onSubmit={submitSignIn}>
              <button type="button" onClick={back} className="label mb-6 hover:text-navy-600">
                ← Back
              </button>

              <h1 className="font-display text-[2.6rem] leading-[1.1] tracking-tight text-navy-900">
                Welcome back.
              </h1>
              <p className="mt-3 text-sm text-navy-900/55">
                Sign in as <span className="font-medium text-navy-800">{email}</span>.
              </p>

              <label className="label mt-8 block">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPw(e.target.value)}
                required
                autoFocus
                autoComplete="current-password"
                className="input mt-1.5"
              />

              {err && <p className="mt-3 text-xs leading-relaxed text-clay">{err}</p>}

              <button type="submit" disabled={busy} className="btn-primary mt-5 w-full">
                {busy ? "Signing in…" : "Sign in"}
                {!busy && <ArrowRight size={15} />}
              </button>
            </form>
          )}
        </div>

        {/* Only makes the residency promise when the residency is real. */}
        <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.12em] text-navy-900/35">
          <ShieldCheck size={11} />
          {SOVEREIGN_INFERENCE
            ? "KSA-resident · No egress · Powered by MeshNet"
            : "Powered by MeshNet"}
        </div>
      </div>

      {/* Date palms in Wadi Sharma, NEOM Nature Reserve. Photo by NEOM (Unsplash License). */}
      <div className="relative hidden overflow-hidden bg-navy-900 lg:block lg:w-[54%]">
        <img
          src="https://images.unsplash.com/photo-1682695796795-cc287af78a2b?q=80&w=2000&auto=format&fit=crop"
          alt="Date palms in Wadi Sharma, NEOM Nature Reserve, Saudi Arabia"
          className="absolute inset-0 h-full w-full object-cover"
        />
        <div className="absolute inset-0 bg-navy-900/25" />
        <div className="absolute inset-x-0 bottom-0 h-3/4 bg-gradient-to-t from-navy-900 via-navy-900/85 to-transparent" />

        <div className="absolute inset-x-0 bottom-0 p-12">
          <p className="max-w-md font-display text-3xl leading-snug text-white">
            Every milestone confirmed from orbit — before a single riyal moves.
          </p>
          <p className="mt-3 max-w-md text-sm leading-relaxed text-white/60">
            EFund pairs each funding tranche with the satellite layer that verifies it. The
            imagery agrees, or the money stays put.
          </p>
          <p className="mt-6 font-mono text-[10px] uppercase tracking-[0.12em] text-white/35">
            Wadi Sharma · NEOM Nature Reserve
          </p>
        </div>
      </div>
    </div>
  );
}
