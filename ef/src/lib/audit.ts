/**
 * Audit trail.
 *
 * ef.audit_log is append-only at the database level — there is no UPDATE or DELETE policy,
 * so not even an org admin can rewrite history. Every analytical action gets logged with the
 * actor, the AOI they were looking at, and which source layers fed the answer. That's what
 * makes the "regulator-inspectable" claim real rather than marketing.
 */

import { supabase } from "./supabase";
import type { Aoi } from "./types";

export type AuditAction =
  | "aoi.select"
  | "ask.query"
  | "layer.toggle"
  | "initiative.create"
  | "initiative.update"
  | "poi.create"
  | "poi.advance"
  | "report.generate"
  | "report.view"
  | "alert.resolve"
  | "auth.login";

export async function logAudit(entry: {
  orgId: string;
  action: AuditAction;
  targetType?: string;
  targetId?: string;
  aoi?: Aoi | null;
  sourceLayers?: string[];
  outputs?: Record<string, unknown>;
}): Promise<void> {
  const { error } = await supabase.from("audit_log").insert({
    org_id: entry.orgId,
    action: entry.action,
    target_type: entry.targetType ?? null,
    target_id: entry.targetId ?? null,
    aoi_geom: entry.aoi ? (entry.aoi.geometry as unknown as string) : null,
    source_layers: entry.sourceLayers ?? null,
    outputs: entry.outputs ?? null,
    user_agent: navigator.userAgent,
  });

  // An audit write must never take the app down, but it must never fail silently either.
  if (error) console.error("[EF/audit] failed to record action:", entry.action, error.message);
}
