import { ArrowUpRight, Leaf, ShieldCheck, TriangleAlert } from "lucide-react";

import { Empty, Progress, Stat, StatusDot } from "../components/ui";
import { navigate } from "../hooks/useEf";
import { area, money, moneyFull, num } from "../lib/format";
import type { Disbursement, Fund, Initiative, Poi } from "../lib/types";

export default function Overview({
  fund,
  initiatives,
  disbursements,
  pois,
}: {
  fund: Fund | null;
  initiatives: Initiative[];
  disbursements: Disbursement[];
  pois: Poi[];
}) {
  const capital = fund?.total_capital ?? 0;
  const committed = initiatives.reduce((s, i) => s + (i.budget_total ?? 0), 0);
  const disbursed = disbursements
    .filter((d) => d.status === "paid")
    .reduce((s, d) => s + d.amount, 0);
  const co2 = initiatives.reduce((s, i) => s + (i.co2_offset_tonnes ?? 0), 0);
  const km2 = initiatives.reduce((s, i) => s + (i.area_km2 ?? 0), 0);
  const critical = pois.filter((p) => p.severity === "critical" || p.severity === "high");

  return (
    <div className="animate-fade-up space-y-8">
      <header>
        <h1 className="font-display text-4xl tracking-tight">
          {fund?.name ?? "Portfolio"}
        </h1>
        <p className="mt-1.5 text-sm text-forest-900/50">
          {fund?.fiscal_year ? `Fiscal year ${fund.fiscal_year} · ` : ""}
          Every tranche released against satellite-verified evidence.
        </p>
      </header>

      {/* Capital flow: committed vs. actually released. The gap is the story —
          it's the money the imagery hasn't cleared yet. */}
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Fund capital"
          value={money(capital)}
          sub={fund ? moneyFull(capital, fund.currency) : undefined}
        />
        <Stat
          label="Committed"
          value={money(committed)}
          sub={
            <div className="space-y-1.5">
              <Progress value={committed} max={capital} />
              <span>{capital ? ((committed / capital) * 100).toFixed(1) : 0}% of capital</span>
            </div>
          }
        />
        <Stat
          label="Disbursed"
          value={money(disbursed)}
          accent
          sub={
            <div className="space-y-1.5">
              <Progress value={disbursed} max={committed} verified />
              <span className="flex items-center gap-1 text-verify-600">
                <ShieldCheck size={11} /> all satellite-verified
              </span>
            </div>
          }
        />
        <Stat
          label="Impact"
          value={
            <span className="flex items-baseline gap-1.5">
              {num(co2)}
              <span className="font-sans text-sm text-forest-900/40">t CO₂/yr</span>
            </span>
          }
          sub={
            <span className="flex items-center gap-1">
              <Leaf size={11} /> across {area(km2)}
            </span>
          }
        />
      </section>

      {/* Anything the satellites flagged that a human hasn't closed out. */}
      {critical.length > 0 && (
        <section className="card border-clay/25 bg-clay/[0.03] p-5">
          <div className="flex items-center gap-2 text-sm font-medium text-clay">
            <TriangleAlert size={15} />
            {critical.length} unresolved {critical.length === 1 ? "finding" : "findings"} in the field
          </div>
          <div className="mt-3 space-y-2">
            {critical.slice(0, 3).map((p) => (
              <div
                key={p.id}
                className="flex items-center justify-between border-t border-line pt-2 text-sm"
              >
                <span className="text-forest-900/75">{p.name}</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-forest-900/40">
                  {p.status.replace(/_/g, " ")}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Initiatives */}
      <section>
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="font-display text-2xl">Initiatives</h2>
          <button
            onClick={() => navigate("/initiatives")}
            className="flex items-center gap-1 text-xs text-forest-600 hover:underline"
          >
            View all <ArrowUpRight size={13} />
          </button>
        </div>

        {initiatives.length === 0 ? (
          <Empty
            title="No initiatives yet"
            body="Once initiatives are funded they'll appear here, each bound to a geofence and a verification layer."
          />
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {initiatives.map((i) => {
              const used = i.budget_used ?? 0;
              const total = i.budget_total ?? 0;
              return (
                <button
                  key={i.id}
                  onClick={() => navigate(`/initiatives/${i.id}`)}
                  className="card group p-5 text-left transition hover:shadow-lift"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h3 className="truncate font-display text-xl leading-tight">{i.name}</h3>
                      {i.grantee && (
                        <p className="mt-1 truncate text-xs text-forest-900/45">{i.grantee}</p>
                      )}
                    </div>
                    <ArrowUpRight
                      size={16}
                      className="shrink-0 text-forest-900/20 transition group-hover:text-forest-600"
                    />
                  </div>

                  <div className="mt-4 flex items-center justify-between text-xs">
                    <StatusDot status={i.status} />
                    <span className="font-mono uppercase tracking-wider text-forest-900/35">
                      {i.sector}
                    </span>
                  </div>

                  <div className="mt-4">
                    <div className="tnum mb-1.5 flex justify-between text-xs">
                      <span className="text-forest-900/50">
                        {money(used)} <span className="text-forest-900/30">of {money(total)}</span>
                      </span>
                      <span className="font-medium text-forest-700">
                        {total ? ((used / total) * 100).toFixed(0) : 0}%
                      </span>
                    </div>
                    <Progress value={used} max={total} />
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
