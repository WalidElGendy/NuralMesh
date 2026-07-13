import type { ReactNode } from "react";
import { Check, Clock, Loader, ShieldCheck, X } from "lucide-react";
import type { DisbursementStatus, MilestoneStatus } from "../lib/types";

export function Stat({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
}  & { accent?: boolean }) {
  return (
    <div className="card p-5">
      <div className="label">{label}</div>
      <div
        className={`tnum mt-2 font-display text-3xl leading-none ${
          // `accent` marks a figure that is green because it was verified — disbursed
          // capital. Not decoration.
          accent ? "text-verify-600" : "text-navy-900"
        }`}
      >
        {value}
      </div>
      {sub && <div className="mt-2 text-xs text-navy-900/50">{sub}</div>}
    </div>
  );
}

export function Progress({ value, max, verified }: { value: number; max: number; verified?: boolean }) {
  const p = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-paper-sunk">
      <div
        className={`h-full rounded-full transition-[width] duration-700 ${
          verified ? "bg-verify-500" : "bg-navy-600"
        }`}
        style={{ width: `${p}%` }}
      />
    </div>
  );
}

const MILESTONE_STYLE: Record<MilestoneStatus, { cls: string; icon: ReactNode; text: string }> = {
  // Green here is load-bearing: it means the imagery agreed. Nothing else in the UI
  // is allowed to be green, so a scan of the page shows exactly what's been proven.
  verified: {
    cls: "bg-verify-100 text-verify-700",
    icon: <ShieldCheck size={11} />,
    text: "Satellite-verified",
  },
  in_review: {
    cls: "bg-sand/15 text-[#8A6F12]",
    icon: <Loader size={11} />,
    text: "In review",
  },
  pending: {
    cls: "bg-paper-sunk text-forest-900/45",
    icon: <Clock size={11} />,
    text: "Pending",
  },
  failed: { cls: "bg-clay/12 text-clay", icon: <X size={11} />, text: "Failed" },
};

export function MilestoneBadge({ status }: { status: MilestoneStatus }) {
  const s = MILESTONE_STYLE[status];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${s.cls}`}
    >
      {s.icon}
      {s.text}
    </span>
  );
}

const DISB_STYLE: Record<DisbursementStatus, string> = {
  // Money that actually moved is green — it only moved because the imagery cleared it.
  paid: "bg-verify-100 text-verify-700",
  approved: "bg-verify-50 text-verify-600",
  requested: "bg-sand/15 text-[#8A6F12]",
  held: "bg-paper-sunk text-forest-900/45",
  rejected: "bg-clay/12 text-clay",
};

export function DisbursementBadge({ status }: { status: DisbursementStatus }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium capitalize ${DISB_STYLE[status]}`}
    >
      {status === "paid" && <Check size={11} />}
      {status}
    </span>
  );
}

export function StatusDot({ status }: { status: string }) {
  const color =
    status === "active"
      ? "bg-forest-500"
      : status === "planning"
        ? "bg-sand"
        : status === "on_hold"
          ? "bg-clay"
          : "bg-forest-900/20";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs capitalize text-forest-900/60">
      <span className={`h-1.5 w-1.5 rounded-full ${color}`} />
      {status.replace("_", " ")}
    </span>
  );
}

export function Empty({ title, body }: { title: string; body: string }) {
  return (
    <div className="card flex flex-col items-center justify-center px-6 py-16 text-center">
      <h3 className="font-display text-xl text-forest-900">{title}</h3>
      <p className="mt-1.5 max-w-sm text-sm text-forest-900/50">{body}</p>
    </div>
  );
}
