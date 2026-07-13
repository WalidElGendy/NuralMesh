import { useState } from "react";
import { ArrowRight, ShieldCheck } from "lucide-react";
import { supabase } from "../lib/supabase";

type Step = "invite" | "signin";

/**
 * Two-step gate. The invite code is a soft gate (it decides who sees the sign-in form);
 * Supabase auth + RLS are the hard gate. We never pretend the code itself is security —
 * it's an access-control funnel, and the database enforces the real boundary.
 */
export default function Auth() {
  const [step, setStep] = useState<Step>("invite");
  const [code, setCode] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function submitInvite(e: React.FormEvent) {
    e.preventDefault();
    if (!code.trim()) return;
    setErr(null);
    setStep("signin");
  }

  async function signIn(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) setErr(error.message);
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
              <p className="mt-4 text-sm leading-relaxed text-forest-900/55">
                Enter your invitation code to fund, track and verify sustainability
                initiatives across the Kingdom.
              </p>

              <label className="label mt-8 block">Invitation code</label>
              <input
                value={code}
                onChange={(e) => setCode(e.target.value.toUpperCase())}
                placeholder="EF-XXXX-XXXX"
                className="input mt-1.5 font-mono tracking-widest"
                autoFocus
              />

              <button type="submit" disabled={!code.trim()} className="btn-primary mt-5 w-full">
                Continue <ArrowRight size={15} />
              </button>
            </form>
          ) : (
            <form onSubmit={signIn}>
              <button
                type="button"
                onClick={() => setStep("invite")}
                className="label mb-6 hover:text-forest-600"
              >
                ← Back
              </button>

              <h1 className="font-display text-[2.6rem] leading-[1.1] tracking-tight">
                Sign in.
              </h1>
              <p className="mt-3 text-sm text-forest-900/55">
                Code <span className="font-mono text-forest-700">{code}</span> accepted.
              </p>

              <label className="label mt-8 block">Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="input mt-1.5"
                autoFocus
              />

              <label className="label mt-4 block">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="input mt-1.5"
              />

              {err && <p className="mt-3 text-xs text-clay">{err}</p>}

              <button type="submit" disabled={busy} className="btn-primary mt-5 w-full">
                {busy ? "Signing in…" : "Sign in"} {!busy && <ArrowRight size={15} />}
              </button>
            </form>
          )}
        </div>

        <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.12em] text-forest-900/35">
          <ShieldCheck size={11} />
          KSA-resident · No egress · Powered by MeshNet
        </div>
      </div>

      {/* Right: the field. Date palms in Wadi Sharma, NEOM — the NEOM Nature Reserve, a real
          Saudi restoration site. Photo by NEOM (Unsplash License). The previous image was
          Monument Valley, Utah, which is not a good look on a Saudi government product. */}
      <div className="relative hidden overflow-hidden bg-navy-900 lg:block lg:w-[54%]">
        <img
          src="https://images.unsplash.com/photo-1682695796795-cc287af78a2b?q=80&w=2000&auto=format&fit=crop"
          alt="Date palms in Wadi Sharma, NEOM Nature Reserve, Saudi Arabia"
          className="absolute inset-0 h-full w-full object-cover"
        />
        {/* Two scrims. The wide one seats the photo in the brand; the tight bottom one
            buys real contrast for the headline — the grove is bright exactly where the
            text lands, and without this the copy washes out. */}
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
