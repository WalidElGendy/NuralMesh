import { useState } from "react";
import { ArrowRight, ShieldCheck } from "lucide-react";
import { supabase } from "../lib/supabase";
import { claimInvite, verifyInvite } from "../lib/invite";
import { SOVEREIGN_INFERENCE } from "../lib/mesh";

type Step = "invite" | "signin";

/**
 * Two-step gate.
 *
 * Step 1 checks (email, code) against MeshNet's shared `invites` table via an edge function
 * running under the service role — the browser can never read that table directly, or the
 * valid codes would simply be listable.
 *
 * The code is an access funnel, not the security boundary. Supabase auth + RLS are. We keep
 * both, because a valid code with no account still gets you nothing.
 */
export default function Auth() {
  const [step, setStep] = useState<Step>("invite");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submitInvite(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);

    const res = await verifyInvite(email, code);

    if (!res.valid) {
      // An already-used code is the one case worth being specific about — it's almost
      // always a returning user, and sending them round the loop again is just cruel.
      setErr(res.reason ?? "That invitation code isn't valid for this email.");
      setBusy(false);
      return;
    }

    setBusy(false);
    setStep("signin");
  }

  async function signIn(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);

    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) {
      setErr(error.message);
      setBusy(false);
      return;
    }

    // Burn the invite only now — after a real session exists. Verifying alone must never
    // consume it, or a stranger could void someone else's code just by typing it.
    await claimInvite(email, code);
    setBusy(false);
  }

  return (
    <div className="flex min-h-screen">
      {/* Left: the form */}
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
          {step === "invite" ? (
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
          ) : (
            <form onSubmit={signIn}>
              <button
                type="button"
                onClick={() => {
                  setStep("invite");
                  setErr(null);
                }}
                className="label mb-6 hover:text-navy-600"
              >
                ← Back
              </button>

              <h1 className="font-display text-[2.6rem] leading-[1.1] tracking-tight text-navy-900">
                Welcome.
              </h1>
              <p className="mt-3 text-sm text-navy-900/55">
                Invitation accepted for{" "}
                <span className="font-medium text-navy-800">{email}</span>.
              </p>

              <label className="label mt-8 block">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoFocus
                className="input mt-1.5"
              />

              {err && <p className="mt-3 text-xs text-clay">{err}</p>}

              <button type="submit" disabled={busy} className="btn-primary mt-5 w-full">
                {busy ? "Signing in…" : "Sign in"}
                {!busy && <ArrowRight size={15} />}
              </button>
            </form>
          )}
        </div>

        {/* This is the most public claim in the whole product — it sits on an unauthenticated
            page. It only makes the residency promise when the residency is real. */}
        <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.12em] text-navy-900/35">
          <ShieldCheck size={11} />
          {SOVEREIGN_INFERENCE
            ? "KSA-resident · No egress · Powered by MeshNet"
            : "Powered by MeshNet"}
        </div>
      </div>

      {/* Right: the field. Date palms in Wadi Sharma, NEOM Nature Reserve — a real Saudi
          restoration site. Photo by NEOM (Unsplash License). */}
      <div className="relative hidden overflow-hidden bg-navy-900 lg:block lg:w-[54%]">
        <img
          src="https://images.unsplash.com/photo-1682695796795-cc287af78a2b?q=80&w=2000&auto=format&fit=crop"
          alt="Date palms in Wadi Sharma, NEOM Nature Reserve, Saudi Arabia"
          className="absolute inset-0 h-full w-full object-cover"
        />
        {/* Two scrims: a wide tint to seat the photo in the brand, and a tight bottom one to
            buy real contrast — the grove is bright exactly where the copy lands. */}
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
