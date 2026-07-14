import type { ReactNode } from "react";
import {
  AlertTriangle,
  FileText,
  Globe2,
  LayoutGrid,
  LogOut,
  Map as MapIcon,
  ScrollText,
  ShieldCheck,
} from "lucide-react";

import { navigate, useRoute } from "../hooks/useEf";
import { supabase } from "../lib/supabase";
import { SOVEREIGN_INFERENCE } from "../lib/mesh";
import type { Role } from "../lib/types";

const NAV = [
  { path: "/", label: "Overview", icon: LayoutGrid },
  { path: "/initiatives", label: "Initiatives", icon: Globe2 },
  { path: "/map", label: "Earth Intelligence", icon: MapIcon },
  { path: "/reports", label: "Reports", icon: FileText },
  { path: "/audit", label: "Audit trail", icon: ScrollText },
];

export default function Shell({
  children,
  role,
  email,
  bare,
}: {
  children: ReactNode;
  role: Role | null;
  email?: string;
  /** The map wants the full canvas — no padding, no scroll container. */
  bare?: boolean;
}) {
  const route = useRoute();

  return (
    <div className="flex h-screen">
      <aside className="flex w-60 shrink-0 flex-col border-r border-line bg-paper-raised">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <img src="/logo.svg" alt="" className="h-8 w-8" />
          <div>
            <div className="font-display text-base leading-none text-navy-900">EFund</div>
            <div dir="rtl" className="mt-1 text-[11px] leading-none text-navy-900/45">
              صندوق البيئة
            </div>
          </div>
        </div>

        <nav className="flex-1 space-y-0.5 px-3 py-2">
          {NAV.map(({ path, label, icon: Icon }) => {
            const active =
              path === "/" ? route === "/" : route.startsWith(path);
            return (
              <button
                key={path}
                onClick={() => navigate(path)}
                className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition ${
                  active
                    ? "bg-forest-50 font-medium text-forest-700"
                    : "text-forest-900/55 hover:bg-paper-sunk hover:text-forest-900"
                }`}
              >
                <Icon size={15} strokeWidth={active ? 2.2 : 1.8} />
                {label}
              </button>
            );
          })}
        </nav>

        <div className="border-t border-line p-3">
          {/* Tell the truth about where inference runs. The sovereign claim goes back the
              moment the orchestrator is deployed and routing to KSA GPU nodes — not before. */}
          {SOVEREIGN_INFERENCE ? (
            <div className="rounded-lg bg-verify-50 px-3 py-2.5">
              <div className="flex items-center gap-1.5 text-[10px] font-medium text-verify-700">
                <ShieldCheck size={11} />
                Sovereign compute
              </div>
              <p className="mt-1 text-[10px] leading-relaxed text-navy-900/45">
                Inference runs on MeshNet GPU nodes inside the Kingdom.
              </p>
            </div>
          ) : (
            <div className="rounded-lg bg-amber-50 px-3 py-2.5">
              <div className="flex items-center gap-1.5 text-[10px] font-medium text-amber-800">
                <AlertTriangle size={11} />
                Inference not yet sovereign
              </div>
              <p className="mt-1 text-[10px] leading-relaxed text-amber-900/60">
                Prompts are served by an external provider. Not cleared for classified data.
              </p>
            </div>
          )}

          <div className="mt-3 flex items-center justify-between px-1">
            <div className="min-w-0">
              <div className="truncate text-xs text-forest-900/70">{email}</div>
              {role && (
                <div className="text-[10px] uppercase tracking-wider text-forest-900/35">
                  {role}
                </div>
              )}
            </div>
            <button
              onClick={() => supabase.auth.signOut()}
              className="shrink-0 rounded p-1.5 text-forest-900/40 transition hover:bg-paper-sunk hover:text-forest-900"
              title="Sign out"
            >
              <LogOut size={14} />
            </button>
          </div>
        </div>
      </aside>

      <main className={bare ? "min-w-0 flex-1" : "min-w-0 flex-1 overflow-y-auto"}>
        {bare ? children : <div className="mx-auto max-w-6xl px-8 py-8">{children}</div>}
      </main>
    </div>
  );
}
