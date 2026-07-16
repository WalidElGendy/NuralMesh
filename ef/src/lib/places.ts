/**
 * Writes for map-created places.
 *
 * Geometry can't go through PostgREST as GeoJSON (a geography column won't cast GeoJSON text),
 * so these call PostGIS RPCs that build the geometry server-side. RLS still applies inside the
 * RPCs, so a caller can only write within their own org and only if their role permits.
 *
 * The RPCs live in the `public` schema, so we call them through `supabasePublic`.
 */

import { supabasePublic } from "./supabase";
import type { Selection } from "./types";

export type Severity = "low" | "medium" | "high" | "critical";

/** Save a pin, or a fence, as a monitored POI. Returns the new POI id. */
export async function createPoi(opts: {
  name: string;
  severity: Severity;
  selection: Selection;
  poiType?: string;
}): Promise<string> {
  const { name, severity, selection, poiType } = opts;
  const { data, error } = await supabasePublic.rpc("ef_create_poi", {
    p_name: name,
    p_severity: severity,
    p_lng: selection.lng,
    p_lat: selection.lat,
    p_poi_type: poiType ?? null,
    p_initiative: null,
    // Keep the fence polygon on the POI when the selection is an area.
    p_polygon: selection.aoi ? selection.aoi.geometry : null,
  });
  if (error) throw new Error(error.message);
  return data as string;
}

/** Promote a ring-fence into a funded initiative. Returns the new initiative id. */
export async function createInitiative(opts: {
  name: string;
  selection: Selection;
  sector?: string;
  mandate?: string;
}): Promise<string> {
  const { name, selection, sector, mandate } = opts;
  if (!selection.aoi) throw new Error("An initiative needs a drawn area, not a single pin.");
  const { data, error } = await supabasePublic.rpc("ef_create_initiative", {
    p_name: name,
    p_polygon: selection.aoi.geometry,
    p_sector: sector ?? null,
    p_mandate: mandate ?? null,
  });
  if (error) throw new Error(error.message);
  return data as string;
}

/** Raise a field alert or set a standing rule on a POI (or initiative). */
export async function createAlert(opts: {
  severity: Severity;
  message: string;
  poiId?: string;
  initiativeId?: string;
  rule?: Record<string, unknown>;
}): Promise<string> {
  const { severity, message, poiId, initiativeId, rule } = opts;
  const { data, error } = await supabasePublic.rpc("ef_create_alert", {
    p_severity: severity,
    p_message: message,
    p_poi: poiId ?? null,
    p_initiative: initiativeId ?? null,
    p_rule: rule ?? {},
  });
  if (error) throw new Error(error.message);
  return data as string;
}
