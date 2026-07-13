import { useState } from "react";
import { Cpu, FileText, Sparkles } from "lucide-react";

import { Empty } from "../components/ui";
import { useReports } from "../hooks/useEf";
import { ask } from "../lib/mesh";
import { supabase } from "../lib/supabase";
import { logAudit } from "../lib/audit";
import { date } from "../lib/format";
import type { Initiative, Report } from "../lib/types";

const KINDS: { key: Report["kind"]; label: string; blurb: string }[] = [
  { key: "exec_brief", label: "Executive brief", blurb: "Board-level summary of status and risk." },
  { key: "progress", label: "Progress report", blurb: "Milestones, disbursement, verification." },
  { key: "regulatory", label: "Regulatory report", blurb: "Compliance posture against mandate." },
  { key: "technical", label: "Technical deep-dive", blurb: "Layer-by-layer evidence." },
];

export default function Reports({
  orgId,
  initiatives,
}: {
  orgId: string;
  initiatives: Initiative[];
}) {
  const { reports, refresh } = useReports(orgId);
  const [kind, setKind] = useState<Report["kind"]>("exec_brief");
  const [initiativeId, setInitiativeId] = useState<string>(initiatives[0]?.id ?? "");
  const [lang, setLang] = useState<"en" | "ar">("en");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [servedBy, setServedBy] = useState<string | null>(null);

  const initiative = initiatives.find((i) => i.id === initiativeId);

  async function generate() {
    if (!initiative || busy) return;
    setBusy(true);
    setDraft("");
    setServedBy(null);

    const label = KINDS.find((k) => k.key === kind)!.label;

    // The analyst agent is just MeshNet with a tightly-scoped brief. Same sovereign path
    // as the map chat — the report is drafted on a GPU node inside the Kingdom.
    const prompt = [
      `You are the analyst inside EFund, the Saudi Environment Fund's oversight platform.`,
      `Draft a ${label} for the initiative below. Be concise, factual and specific.`,
      `Use markdown headings. Do not invent figures beyond those given —`,
      `where evidence is missing, say what capture would be needed.`,
      lang === "ar" ? `Write in Arabic.` : `Write in English.`,
      ``,
      `INITIATIVE`,
      `- Name: ${initiative.name}`,
      `- Sector: ${initiative.sector ?? "—"}`,
      `- Grantee: ${initiative.grantee ?? "—"}`,
      `- Mandate: ${initiative.mandate ?? "—"}`,
      `- Status: ${initiative.status}`,
      `- Budget: ${initiative.budget_used ?? 0} of ${initiative.budget_total ?? 0} SAR`,
      `- Area: ${initiative.area_km2 ?? "—"} km²`,
      `- CO2 offset: ${initiative.co2_offset_tonnes ?? "—"} t/yr`,
    ].join("\n");

    await ask(
      { message: prompt, mode: "auto" },
      {
        onToken: (t) => setDraft((d) => d + t),
        onDone: async (meta) => {
          setServedBy(meta.served_by);
          // Persist with the mesh job that produced it — provenance for the audit trail.
          await supabase.from("reports").insert({
            org_id: orgId,
            initiative_id: initiativeId,
            kind,
            title: `${label} — ${initiative.name}`,
            lang,
            content_md: draft,
            status: "ready",
            mesh_job_id: meta.message_id,
            model: meta.model,
          });
          void logAudit({
            orgId,
            action: "report.generate",
            targetType: "initiative",
            targetId: initiativeId,
            outputs: { kind, served_by: meta.served_by, model: meta.model },
          });
          await refresh();
          setBusy(false);
        },
        onError: (e) => {
          setDraft(`Could not reach MeshNet: ${e.message}`);
          setBusy(false);
        },
      },
    );
  }

  return (
    <div className="animate-fade-up space-y-8">
      <header>
        <h1 className="font-display text-4xl tracking-tight">Reports</h1>
        <p className="mt-1.5 text-sm text-forest-900/50">
          Analyst-grade documents, drafted on MeshNet GPU nodes inside the Kingdom.
        </p>
      </header>

      <section className="card p-6">
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <label className="label mb-1.5 block">Initiative</label>
            <select
              value={initiativeId}
              onChange={(e) => setInitiativeId(e.target.value)}
              className="input"
            >
              {initiatives.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label mb-1.5 block">Type</label>
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value as Report["kind"])}
              className="input"
            >
              {KINDS.map((k) => (
                <option key={k.key} value={k.key}>
                  {k.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label mb-1.5 block">Language</label>
            <select
              value={lang}
              onChange={(e) => setLang(e.target.value as "en" | "ar")}
              className="input"
            >
              <option value="en">English</option>
              <option value="ar">العربية</option>
            </select>
          </div>
        </div>

        <div className="mt-4 flex items-center justify-between">
          <p className="text-xs text-forest-900/45">
            {KINDS.find((k) => k.key === kind)?.blurb}
          </p>
          <button onClick={generate} disabled={busy || !initiative} className="btn-primary">
            <Sparkles size={14} />
            {busy ? "Drafting…" : "Generate"}
          </button>
        </div>
      </section>

      {(draft || busy) && (
        <section className="card p-6">
          {servedBy && (
            <div className="mb-4 flex items-center gap-1.5 border-b border-line pb-3 font-mono text-[10px] uppercase tracking-wider text-forest-600">
              <Cpu size={11} /> drafted on MeshNet node · {servedBy}
            </div>
          )}
          <article className="whitespace-pre-wrap text-sm leading-relaxed text-forest-900/80">
            {draft || <span className="text-forest-900/35">Routing through the mesh…</span>}
          </article>
        </section>
      )}

      <section>
        <h2 className="mb-4 font-display text-2xl">Archive</h2>
        {reports.length === 0 ? (
          <Empty title="No reports yet" body="Generated reports are stored here with the mesh job that produced them." />
        ) : (
          <div className="space-y-2">
            {reports.map((r) => (
              <div key={r.id} className="card flex items-center gap-3 p-4">
                <FileText size={16} className="shrink-0 text-forest-900/30" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{r.title}</div>
                  <div className="mt-0.5 font-mono text-[10px] uppercase tracking-wider text-forest-900/40">
                    {r.kind.replace(/_/g, " ")} · {r.lang} · {date(r.created_at)}
                    {r.model && ` · ${r.model}`}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
