import { useState } from "react";
import {
  ArrowLeft,
  Banknote,
  Info,
  Lock,
  Satellite,
  TrendingDown,
  TrendingUp,
  Minus,
} from "lucide-react";

import { DisbursementBadge, MilestoneBadge, Progress, StatusDot } from "../components/ui";
import { useInitiativeDetail, navigate } from "../hooks/useEf";
import { supabase } from "../lib/supabase";
import { logAudit } from "../lib/audit";
import { area, date, money, moneyFull, num } from "../lib/format";
import type { Initiative, Milestone, Role } from "../lib/types";

export default function InitiativeDetail({
  initiative,
  role,
  orgId,
  onChanged,
}: {
  initiative: Initiative;
  role: Role | null;
  orgId: string;
  onChanged: () => void;
}) {
  const { kpis, milestones, disbursements, latestRun, refresh } = useInitiativeDetail(
    initiative.id,
  );
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const canMoveMoney = role === "operator" || role === "admin";
  const used = initiative.budget_used ?? 0;
  const total = initiative.budget_total ?? 0;
  const paid = disbursements
    .filter((d) => d.status === "paid")
    .reduce((s, d) => s + d.amount, 0);

  /** Attempt a release. The database trigger is the real gate — if the milestone isn't
   *  satellite-verified, Postgres refuses and we surface the exact reason. */
  async function release(m: Milestone) {
    setErr(null);
    setBusy(m.id);

    const tranche = total / Math.max(milestones.length, 1);
    const { error } = await supabase.from("disbursements").insert({
      org_id: orgId,
      initiative_id: initiative.id,
      milestone_id: m.id,
      amount: Math.round(tranche),
      status: "approved",
      note: `Tranche released on ${m.name}`,
    });

    if (error) {
      setErr(error.message);
    } else {
      void logAudit({
        orgId,
        action: "initiative.update",
        targetType: "disbursement",
        targetId: m.id,
        outputs: { milestone: m.name, amount: Math.round(tranche) },
      });
      await refresh();
      onChanged();
    }
    setBusy(null);
  }

  return (
    <div className="animate-fade-up space-y-8">
      <button
        onClick={() => navigate("/initiatives")}
        className="flex items-center gap-1.5 text-xs text-forest-900/50 transition hover:text-forest-700"
      >
        <ArrowLeft size={13} /> Initiatives
      </button>

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl tracking-tight">{initiative.name}</h1>
          {initiative.name_ar && (
            <p dir="rtl" className="mt-1 font-display text-xl text-forest-900/40">
              {initiative.name_ar}
            </p>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-forest-900/50">
            <StatusDot status={initiative.status} />
            {initiative.grantee && <span>Grantee · {initiative.grantee}</span>}
            <span>
              {date(initiative.start_date)} → {date(initiative.end_date)}
            </span>
            {initiative.area_km2 && <span>{area(initiative.area_km2)}</span>}
          </div>
        </div>
        <button onClick={() => navigate("/map")} className="btn-ghost">
          <Satellite size={14} /> Open in Earth Intelligence
        </button>
      </header>

      {initiative.mandate && (
        <p className="max-w-3xl border-l-2 border-forest-200 pl-4 text-sm leading-relaxed text-forest-900/60">
          {initiative.mandate}
        </p>
      )}

      {/* Budget */}
      <section className="card p-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="label">Budget</div>
            <div className="tnum mt-1.5 font-display text-3xl">
              {moneyFull(used)}{" "}
              <span className="font-sans text-base text-forest-900/35">
                of {moneyFull(total)}
              </span>
            </div>
          </div>
          <div className="text-right">
            <div className="label">Released to date</div>
            <div className="tnum mt-1.5 font-display text-3xl text-forest-600">
              {moneyFull(paid)}
            </div>
          </div>
        </div>
        <div className="mt-4">
          <Progress value={used} max={total} />
        </div>
      </section>

      {/* Milestones — the spine of the product. Each names its verification layer up front. */}
      <section>
        <h2 className="mb-1 font-display text-2xl">Milestones</h2>
        <p className="mb-4 text-sm text-forest-900/50">
          Each milestone declares the satellite layer that will verify it. Funds cannot be
          released until the imagery agrees — enforced in the database, not the interface.
        </p>

        {err && (
          <div className="mb-4 flex items-start gap-2 rounded-lg border border-clay/30 bg-clay/5 p-3 text-xs text-clay">
            <Lock size={13} className="mt-0.5 shrink-0" />
            <span>{err}</span>
          </div>
        )}

        <div className="space-y-3">
          {milestones.map((m) => {
            const released = disbursements.some((d) => d.milestone_id === m.id);
            const releasable = m.status === "verified" && !released && canMoveMoney;
            const run = latestRun(m.id);

            return (
              <div key={m.id} className="card p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2.5">
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-paper-sunk font-mono text-[10px] text-forest-900/50">
                        {m.seq}
                      </span>
                      <h3 className="font-medium">{m.name}</h3>
                      <MilestoneBadge status={m.status} />
                    </div>

                    {m.verification_layer && (
                      <div className="mt-2.5 flex items-center gap-1.5 ps-7 font-mono text-[11px] text-forest-900/45">
                        <Satellite size={11} />
                        verified by <span className="text-forest-600">{m.verification_layer}</span>
                      </div>
                    )}
                    {m.verification_note && (
                      <p className="mt-1.5 ps-7 text-xs leading-relaxed text-forest-900/55">
                        {m.verification_note}
                      </p>
                    )}
                  </div>

                  <div className="text-right">
                    {m.target_value !== null && (
                      <div className="tnum text-sm">
                        <span className="text-forest-900/40">target</span>{" "}
                        {num(m.target_value)} {m.target_unit}
                      </div>
                    )}
                    {m.verified_value !== null && (
                      <div className="tnum text-sm text-forest-600">
                        <span className="text-forest-900/40">actual</span>{" "}
                        {num(m.verified_value)} {m.target_unit}
                      </div>
                    )}
                    <div className="mt-1 text-[11px] text-forest-900/35">
                      due {date(m.due_date)}
                    </div>
                  </div>
                </div>

                {/* The machine's last reading. Shown even when it verified nothing —
                    an honest "couldn't measure this" is itself the evidence. */}
                {run && (
                  <div
                    className={`mt-3 rounded-lg border p-3 ${
                      run.decision === "verified"
                        ? "border-forest-200 bg-forest-50"
                        : run.decision === "failed"
                          ? "border-clay/25 bg-clay/[0.03]"
                          : "border-line bg-paper-sunk/50"
                    }`}
                  >
                    <div className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-forest-900/45">
                      <Satellite size={10} />
                      automated check · {date(run.created_at)}
                      {run.scene_date && <span>· scene {date(run.scene_date)}</span>}
                    </div>

                    <p className="mt-1.5 text-xs leading-relaxed text-forest-900/70">
                      {run.reason}
                    </p>

                    <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[10px] text-forest-900/45">
                      <span>provider · {run.provider}</span>
                      {run.observed_value !== null ? (
                        <span className="text-forest-700">
                          observed · {num(run.observed_value, 2)}
                        </span>
                      ) : (
                        <span className="text-clay">no reading obtained</span>
                      )}
                      <span>decision · {run.decision.replace("_", " ")}</span>
                    </div>
                  </div>
                )}

                <div className="mt-4 flex items-center justify-between border-t border-line pt-3">
                  <span className="text-xs text-forest-900/45">
                    {released
                      ? "Tranche released"
                      : m.status === "verified"
                        ? "Cleared for release"
                        : "Awaiting satellite verification"}
                  </span>

                  {released ? (
                    <DisbursementBadge status="paid" />
                  ) : (
                    <button
                      onClick={() => release(m)}
                      disabled={!releasable || busy === m.id}
                      title={
                        !canMoveMoney
                          ? "Requires operator or admin role"
                          : m.status !== "verified"
                            ? "Milestone is not satellite-verified"
                            : undefined
                      }
                      className={releasable ? "btn-primary" : "btn-ghost opacity-45"}
                    >
                      {m.status === "verified" ? <Banknote size={14} /> : <Lock size={13} />}
                      {busy === m.id ? "Releasing…" : "Release funds"}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
          {milestones.length === 0 && (
            <p className="text-sm text-forest-900/40">No milestones defined.</p>
          )}
        </div>
      </section>

      {/* KPIs with provenance */}
      <section>
        <h2 className="mb-4 font-display text-2xl">Live indicators</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {kpis.map((k) => (
            <div key={k.id} className="card group relative p-4">
              <div className="flex items-start justify-between">
                <span className="label">{k.label}</span>
                {k.source_layer && (
                  <Info size={11} className="text-forest-900/20 group-hover:text-forest-600" />
                )}
              </div>
              <div className="tnum mt-2 flex items-baseline gap-1">
                <span className="font-display text-2xl">{num(k.value, 1)}</span>
                <span className="text-xs text-forest-900/40">{k.unit}</span>
                {k.trend === "up" && <TrendingUp size={13} className="ms-auto text-forest-600" />}
                {k.trend === "down" && <TrendingDown size={13} className="ms-auto text-clay" />}
                {k.trend === "flat" && <Minus size={13} className="ms-auto text-forest-900/25" />}
              </div>

              {/* Provenance on hover — source, method, cadence, confidence. */}
              {k.source_layer && (
                <div className="pointer-events-none absolute inset-x-3 bottom-full z-20 mb-2 hidden rounded-lg bg-forest-900 p-2.5 font-mono text-[10px] leading-relaxed text-white/70 shadow-lift group-hover:block">
                  <div>
                    source · <span className="text-signal">{k.source_layer}</span>
                  </div>
                  {k.method && <div>method · {k.method}</div>}
                  {k.cadence && <div>cadence · {k.cadence}</div>}
                  {k.confidence !== null && (
                    <div>confidence · {(k.confidence * 100).toFixed(0)}%</div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* Ledger */}
      <section>
        <h2 className="mb-4 font-display text-2xl">Disbursement ledger</h2>
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line bg-paper-sunk/50">
                {["Date", "Note", "Status", "Amount"].map((h, idx) => (
                  <th
                    key={h}
                    className={`label px-4 py-2.5 ${idx === 3 ? "text-right" : "text-left"}`}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {disbursements.map((d) => (
                <tr key={d.id} className="border-b border-line last:border-0">
                  <td className="px-4 py-3 text-forest-900/60">
                    {date(d.paid_at ?? d.approved_at ?? d.requested_at)}
                  </td>
                  <td className="px-4 py-3 text-forest-900/75">{d.note ?? "—"}</td>
                  <td className="px-4 py-3">
                    <DisbursementBadge status={d.status} />
                  </td>
                  <td className="tnum px-4 py-3 text-right font-medium">{money(d.amount)}</td>
                </tr>
              ))}
              {disbursements.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-sm text-forest-900/40">
                    Nothing released yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
