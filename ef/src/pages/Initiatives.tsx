import { ArrowUpRight } from "lucide-react";

import { Empty, Progress, StatusDot } from "../components/ui";
import { navigate } from "../hooks/useEf";
import { area, date, money, num } from "../lib/format";
import type { Initiative } from "../lib/types";

export default function Initiatives({ initiatives }: { initiatives: Initiative[] }) {
  return (
    <div className="animate-fade-up space-y-6">
      <header>
        <h1 className="font-display text-4xl tracking-tight">Initiatives</h1>
        <p className="mt-1.5 text-sm text-forest-900/50">
          {initiatives.length} funded {initiatives.length === 1 ? "initiative" : "initiatives"},
          each bound to a geofence and a verification layer.
        </p>
      </header>

      {initiatives.length === 0 ? (
        <Empty title="No initiatives yet" body="Funded initiatives will appear here." />
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line bg-paper-sunk/50">
                {["Initiative", "Sector", "Status", "Area", "CO₂ / yr", "Budget", ""].map(
                  (h, i) => (
                    <th
                      key={h || i}
                      className={`label px-4 py-3 ${i >= 3 && i <= 5 ? "text-right" : "text-left"}`}
                    >
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {initiatives.map((i) => (
                <tr
                  key={i.id}
                  onClick={() => navigate(`/initiatives/${i.id}`)}
                  className="group cursor-pointer border-b border-line transition last:border-0 hover:bg-paper-sunk/40"
                >
                  <td className="px-4 py-3.5">
                    <div className="font-medium text-forest-900">{i.name}</div>
                    {i.grantee && (
                      <div className="mt-0.5 text-xs text-forest-900/45">{i.grantee}</div>
                    )}
                  </td>
                  <td className="px-4 py-3.5">
                    <span className="font-mono text-[10px] uppercase tracking-wider text-forest-900/45">
                      {i.sector}
                    </span>
                  </td>
                  <td className="px-4 py-3.5">
                    <StatusDot status={i.status} />
                  </td>
                  <td className="tnum px-4 py-3.5 text-right text-forest-900/65">
                    {area(i.area_km2)}
                  </td>
                  <td className="tnum px-4 py-3.5 text-right text-forest-900/65">
                    {num(i.co2_offset_tonnes)} t
                  </td>
                  <td className="px-4 py-3.5">
                    <div className="tnum mb-1 text-right text-xs text-forest-900/60">
                      {money(i.budget_used)}{" "}
                      <span className="text-forest-900/30">/ {money(i.budget_total)}</span>
                    </div>
                    <Progress value={i.budget_used ?? 0} max={i.budget_total ?? 0} />
                    <div className="mt-1 text-right text-[10px] text-forest-900/35">
                      ends {date(i.end_date)}
                    </div>
                  </td>
                  <td className="px-4 py-3.5">
                    <ArrowUpRight
                      size={15}
                      className="text-forest-900/20 transition group-hover:text-forest-600"
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
