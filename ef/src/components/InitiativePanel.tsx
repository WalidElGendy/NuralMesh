import { Target, TrendingDown, TrendingUp, Minus, Info } from "lucide-react";
import type { Initiative, Kpi } from "../lib/types";

interface Props {
  initiatives: Initiative[];
  selectedId: string | null;
  kpis: Kpi[];
  onSelect: (id: string | null) => void;
}

const STATUS_COLOR: Record<string, string> = {
  active: "text-signal bg-signal/10",
  planning: "text-sky-400 bg-sky-400/10",
  on_hold: "text-amber-400 bg-amber-400/10",
  completed: "text-zinc-400 bg-zinc-400/10",
  archived: "text-zinc-600 bg-zinc-600/10",
};

export default function InitiativePanel({ initiatives, selectedId, kpis, onSelect }: Props) {
  const selected = initiatives.find((i) => i.id === selectedId) ?? null;

  if (!selected) {
    return (
      <div className="space-y-2 p-4">
        <div className="mb-3 flex items-center gap-1.5 text-[10px] uppercase tracking-widest text-zinc-500">
          <Target size={11} /> Initiatives
        </div>
        {initiatives.length === 0 && (
          <p className="text-xs text-zinc-600">
            No initiatives yet. Draw an AOI and promote it into one.
          </p>
        )}
        {initiatives.map((i) => (
          <button
            key={i.id}
            onClick={() => onSelect(i.id)}
            className="w-full rounded-lg border border-edge bg-ink-700 p-3 text-left transition hover:border-signal/40"
          >
            <div className="flex items-start justify-between gap-2">
              <span className="text-sm text-zinc-200">{i.name}</span>
              <span
                className={`shrink-0 rounded px-1.5 py-0.5 font-mono text-[9px] uppercase ${
                  STATUS_COLOR[i.status] ?? ""
                }`}
              >
                {i.status}
              </span>
            </div>
            {i.sector && (
              <div className="mt-1 font-mono text-[10px] uppercase text-zinc-600">{i.sector}</div>
            )}
          </button>
        ))}
      </div>
    );
  }

  const budgetPct =
    selected.budget_total && selected.budget_used
      ? (selected.budget_used / selected.budget_total) * 100
      : null;

  return (
    <div className="space-y-4 p-4">
      <button
        onClick={() => onSelect(null)}
        className="text-[10px] uppercase tracking-widest text-zinc-500 hover:text-signal"
      >
        ← All initiatives
      </button>

      <div>
        <h2 className="text-lg font-semibold text-zinc-100">{selected.name}</h2>
        {selected.name_ar && (
          <p dir="rtl" className="mt-0.5 text-sm text-zinc-500">
            {selected.name_ar}
          </p>
        )}
        {selected.mandate && (
          <p className="mt-2 text-xs leading-relaxed text-zinc-500">{selected.mandate}</p>
        )}
      </div>

      {budgetPct !== null && (
        <div>
          <div className="mb-1 flex justify-between font-mono text-[10px] text-zinc-500">
            <span>BUDGET USED</span>
            <span className="text-zinc-300">{budgetPct.toFixed(0)}%</span>
          </div>
          <div className="h-1 w-full overflow-hidden rounded bg-ink-600">
            <div className="h-full bg-signal" style={{ width: `${Math.min(budgetPct, 100)}%` }} />
          </div>
        </div>
      )}

      {/* KPI grid. Every tile exposes its provenance on hover — source layer, method, confidence.
          A number without a source is just a rumour. */}
      <div className="grid grid-cols-2 gap-2">
        {kpis.map((k) => (
          <div
            key={k.id}
            className="group relative rounded-lg border border-edge bg-ink-700 p-2.5"
          >
            <div className="flex items-center justify-between">
              <span className="font-mono text-[9px] uppercase tracking-wider text-zinc-600">
                {k.label}
              </span>
              {k.source_layer && (
                <Info size={9} className="text-zinc-700 group-hover:text-signal" />
              )}
            </div>
            <div className="mt-1 flex items-baseline gap-1">
              <span className="text-lg font-semibold text-zinc-100">
                {k.value !== null ? k.value.toLocaleString() : "—"}
              </span>
              {k.unit && <span className="text-[10px] text-zinc-500">{k.unit}</span>}
              {k.trend === "up" && <TrendingUp size={11} className="ms-auto text-signal" />}
              {k.trend === "down" && <TrendingDown size={11} className="ms-auto text-red-400" />}
              {k.trend === "flat" && <Minus size={11} className="ms-auto text-zinc-600" />}
            </div>

            {k.source_layer && (
              <div className="pointer-events-none absolute inset-x-0 bottom-full z-10 mb-1 hidden rounded-lg border border-edge bg-ink-900 p-2 font-mono text-[9px] leading-relaxed text-zinc-400 shadow-xl group-hover:block">
                <div>
                  source: <span className="text-signal-dim">{k.source_layer}</span>
                </div>
                {k.method && <div>method: {k.method}</div>}
                {k.cadence && <div>cadence: {k.cadence}</div>}
                {k.confidence !== null && (
                  <div>confidence: {(k.confidence * 100).toFixed(0)}%</div>
                )}
              </div>
            )}
          </div>
        ))}
        {kpis.length === 0 && (
          <p className="col-span-2 text-xs text-zinc-600">No KPIs bound to this initiative yet.</p>
        )}
      </div>
    </div>
  );
}
