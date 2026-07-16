import { useEffect, useState } from "react";
import {
  Banknote,
  Bell,
  FileText,
  MapPin,
  Radar,
  Sparkles,
  Target,
  X,
} from "lucide-react";

import { createAlert, createInitiative, createPoi, type Severity } from "../lib/places";
import { logAudit } from "../lib/audit";
import { formatArea } from "../lib/geo";
import type { Role, Selection } from "../lib/types";

interface Props {
  selection: Selection;
  role: Role | null;
  orgId: string;
  onAsk: (question: string) => void;
  onSaved: () => void;
  onClose: () => void;
}

const SEVERITIES: Severity[] = ["low", "medium", "high", "critical"];
const SEV_STYLE: Record<Severity, string> = {
  low: "bg-verify-500",
  medium: "bg-sand",
  high: "bg-orange-500",
  critical: "bg-clay",
};

export default function ActionCard({ selection, role, orgId, onAsk, onSaved, onClose }: Props) {
  const isArea = selection.kind === "area";
  const existing = selection.existingPoi;

  const [name, setName] = useState(existing?.name ?? "");
  const [severity, setSeverity] = useState<Severity>(
    (existing?.severity as Severity) ?? "medium",
  );
  const [alertMsg, setAlertMsg] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setName(existing?.name ?? "");
    setSeverity((existing?.severity as Severity) ?? "medium");
    setDone(null);
    setErr(null);
    setAlertMsg("");
  }, [selection]);

  const canWrite = role === "analyst" || role === "operator" || role === "admin";
  const canFund = role === "operator" || role === "admin";

  async function run(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setErr(null);
    try {
      await fn();
      setDone(label);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const coord = `${selection.lat.toFixed(4)}°N, ${selection.lng.toFixed(4)}°E`;

  return (
    <div className="w-80 rounded-xl border border-field-line bg-field-900/95 p-3.5 text-white/90 shadow-xl backdrop-blur-md">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-signal">
          {isArea ? <Target size={11} /> : <MapPin size={11} />}
          {existing ? "Selected POI" : isArea ? "Ring-fenced area" : "Dropped pin"}
        </div>
        <button onClick={onClose} className="text-white/40 hover:text-white" title="Clear">
          <X size={14} />
        </button>
      </div>

      <div className="mt-1 font-mono text-[11px] text-white/45">
        {coord}
        {isArea && selection.aoi && ` · ${formatArea(selection.aoi.areaKm2)}`}
      </div>

      {/* Ask + report — available to everyone, straight into the chat. */}
      <div className="mt-3 grid grid-cols-2 gap-2">
        <button
          onClick={() =>
            onAsk(
              isArea
                ? "Give me a concise environmental read on this area — vegetation, water, soil, and anything anomalous."
                : "What's notable about this exact location environmentally?",
            )
          }
          className="flex items-center justify-center gap-1.5 rounded-lg border border-field-line bg-field-800 px-2 py-2 text-xs transition hover:border-signal/40"
        >
          <Sparkles size={13} /> Ask AI
        </button>
        <button
          onClick={() =>
            onAsk(
              "Draft a short field report on this location: what it is, current condition, risks, and a recommended action. Use headings.",
            )
          }
          className="flex items-center justify-center gap-1.5 rounded-lg border border-field-line bg-field-800 px-2 py-2 text-xs transition hover:border-signal/40"
        >
          <FileText size={13} /> Report
        </button>
      </div>

      {canWrite && (
        <>
          <div className="mt-3 border-t border-field-line pt-3">
            <label className="font-mono text-[9px] uppercase tracking-wider text-white/35">
              Name
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={isArea ? "e.g. Wadi Ad-Dawasir sector" : "e.g. Suspected clearance"}
              className="mt-1 w-full rounded-lg border border-field-line bg-field-800 px-2.5 py-1.5 text-xs text-white/90 outline-none placeholder:text-white/25 focus:border-signal/50"
            />

            <div className="mt-2 flex items-center gap-1.5">
              <span className="font-mono text-[9px] uppercase tracking-wider text-white/35">
                Severity
              </span>
              {SEVERITIES.map((s) => (
                <button
                  key={s}
                  onClick={() => setSeverity(s)}
                  className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] capitalize transition ${
                    severity === s ? "bg-white/10 text-white" : "text-white/40 hover:text-white/70"
                  }`}
                >
                  <span className={`h-1.5 w-1.5 rounded-full ${SEV_STYLE[s]}`} />
                  {s}
                </button>
              ))}
            </div>
          </div>

          {/* Save */}
          <div className="mt-3 grid grid-cols-2 gap-2">
            <button
              disabled={!name.trim() || busy !== null}
              onClick={() =>
                run("poi", async () => {
                  const id = await createPoi({ name: name.trim(), severity, selection });
                  void logAudit({
                    orgId,
                    action: "poi.create",
                    targetType: "poi",
                    targetId: id,
                    aoi: selection.aoi ?? null,
                    outputs: { name: name.trim(), severity },
                  });
                  onSaved();
                })
              }
              className="flex items-center justify-center gap-1.5 rounded-lg bg-signal px-2 py-2 text-xs font-medium text-field-900 transition disabled:opacity-30"
            >
              <Radar size={13} />
              {busy === "poi" ? "Saving…" : "Save as POI"}
            </button>
            <button
              disabled={!isArea || !canFund || !name.trim() || busy !== null}
              title={!isArea ? "Draw a fence to create an initiative" : !canFund ? "Operator+ only" : ""}
              onClick={() =>
                run("init", async () => {
                  const id = await createInitiative({ name: name.trim(), selection });
                  void logAudit({
                    orgId,
                    action: "initiative.create",
                    targetType: "initiative",
                    targetId: id,
                    aoi: selection.aoi ?? null,
                    outputs: { name: name.trim() },
                  });
                  onSaved();
                })
              }
              className="flex items-center justify-center gap-1.5 rounded-lg border border-field-line bg-field-800 px-2 py-2 text-xs transition hover:border-signal/40 disabled:opacity-30"
            >
              <Banknote size={13} />
              {busy === "init" ? "…" : "Initiative"}
            </button>
          </div>

          {/* Alerts */}
          <div className="mt-3 border-t border-field-line pt-3">
            <label className="font-mono text-[9px] uppercase tracking-wider text-white/35">
              Alert message
            </label>
            <input
              value={alertMsg}
              onChange={(e) => setAlertMsg(e.target.value)}
              placeholder="e.g. NDVI decline detected — investigate"
              className="mt-1 w-full rounded-lg border border-field-line bg-field-800 px-2.5 py-1.5 text-xs text-white/90 outline-none placeholder:text-white/25 focus:border-signal/50"
            />
            <div className="mt-2 grid grid-cols-2 gap-2">
              <button
                disabled={!alertMsg.trim() || busy !== null}
                onClick={() =>
                  run("dispatch", async () => {
                    const id = await createAlert({
                      severity,
                      message: alertMsg.trim(),
                      poiId: existing?.id,
                    });
                    void logAudit({
                      orgId,
                      action: "alert.resolve",
                      targetType: "alert",
                      targetId: id,
                      outputs: { message: alertMsg.trim(), severity, kind: "field" },
                    });
                    onSaved();
                  })
                }
                className="flex items-center justify-center gap-1.5 rounded-lg border border-field-line bg-field-800 px-2 py-2 text-xs transition hover:border-clay/50 disabled:opacity-30"
              >
                <Bell size={13} />
                {busy === "dispatch" ? "…" : "Dispatch"}
              </button>
              <button
                disabled={!alertMsg.trim() || busy !== null}
                onClick={() =>
                  run("rule", async () => {
                    const id = await createAlert({
                      severity,
                      message: alertMsg.trim(),
                      poiId: existing?.id,
                      rule: { type: "standing", note: alertMsg.trim(), lng: selection.lng, lat: selection.lat },
                    });
                    void logAudit({
                      orgId,
                      action: "alert.resolve",
                      targetType: "alert",
                      targetId: id,
                      outputs: { message: alertMsg.trim(), severity, kind: "standing" },
                    });
                    onSaved();
                  })
                }
                className="flex items-center justify-center gap-1.5 rounded-lg border border-field-line bg-field-800 px-2 py-2 text-xs transition hover:border-signal/40 disabled:opacity-30"
              >
                <Radar size={13} />
                {busy === "rule" ? "…" : "Standing rule"}
              </button>
            </div>
          </div>
        </>
      )}

      {!canWrite && (
        <p className="mt-3 border-t border-field-line pt-3 text-[11px] text-white/40">
          You have view access. Ask the AI or generate a report; saving places and alerts needs
          an analyst role or higher.
        </p>
      )}

      {done && <p className="mt-2 text-[11px] text-signal">Saved ✓</p>}
      {err && <p className="mt-2 text-[11px] text-clay">{err}</p>}
    </div>
  );
}
