import { useEffect, useState } from "react";
import { Lock } from "lucide-react";

import { Empty } from "../components/ui";
import { supabase } from "../lib/supabase";
import type { Role } from "../lib/types";

interface Row {
  id: number;
  action: string;
  target_type: string | null;
  source_layers: string[] | null;
  outputs: Record<string, unknown> | null;
  created_at: string;
}

export default function Audit({ role }: { role: Role | null }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [denied, setDenied] = useState(false);

  useEffect(() => {
    supabase
      .from("audit_log")
      .select("id, action, target_type, source_layers, outputs, created_at")
      .order("created_at", { ascending: false })
      .limit(200)
      .then(({ data, error }) => {
        // RLS restricts the audit log to admins. An empty result for a non-admin
        // is the policy working, not a bug — say so rather than showing a blank page.
        if (error || (role !== "admin" && !data?.length)) setDenied(role !== "admin");
        setRows((data as Row[]) ?? []);
      });
  }, [role]);

  return (
    <div className="animate-fade-up space-y-6">
      <header>
        <h1 className="font-display text-4xl tracking-tight">Audit trail</h1>
        <p className="mt-1.5 flex items-center gap-1.5 text-sm text-forest-900/50">
          <Lock size={13} />
          Append-only. No update or delete policy exists — not even an administrator can rewrite
          history.
        </p>
      </header>

      {denied ? (
        <Empty
          title="Restricted"
          body="The audit trail is visible to administrators only. This restriction is enforced by row-level security in the database."
        />
      ) : rows.length === 0 ? (
        <Empty title="No entries yet" body="Actions across the platform will be recorded here." />
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line bg-paper-sunk/50">
                {["Time", "Action", "Target", "Source layers"].map((h) => (
                  <th key={h} className="label px-4 py-3 text-left">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-line last:border-0">
                  <td className="tnum whitespace-nowrap px-4 py-2.5 text-xs text-forest-900/50">
                    {new Date(r.created_at).toLocaleString("en-GB")}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="rounded bg-paper-sunk px-1.5 py-0.5 font-mono text-[10px] text-forest-700">
                      {r.action}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-xs text-forest-900/60">
                    {r.target_type ?? "—"}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-[10px] text-forest-900/45">
                    {r.source_layers?.join(", ") || "—"}
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
