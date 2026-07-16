// EF domain types — mirrors the `ef` schema in Supabase.

export type Role = "viewer" | "analyst" | "operator" | "admin";

export type InitiativeStatus =
  | "planning"
  | "active"
  | "on_hold"
  | "completed"
  | "archived";

export type MilestoneStatus = "pending" | "in_review" | "verified" | "failed";

export type DisbursementStatus =
  | "requested"
  | "approved"
  | "paid"
  | "held"
  | "rejected";

export type PoiStatus =
  | "identified"
  | "under_assessment"
  | "course_of_action"
  | "approved_dispatched"
  | "resolved";

export type Sector =
  | "environment"
  | "agriculture"
  | "urban"
  | "industrial"
  | "defence"
  | "disaster";

export interface Fund {
  id: string;
  org_id: string;
  name: string;
  name_ar: string | null;
  currency: string;
  total_capital: number;
  fiscal_year: number | null;
}

export interface Initiative {
  id: string;
  org_id: string;
  fund_id: string | null;
  name: string;
  name_ar: string | null;
  sector: Sector | null;
  mandate: string | null;
  status: InitiativeStatus;
  grantee: string | null;
  grantee_ar: string | null;
  budget_total: number | null;
  budget_used: number | null;
  co2_offset_tonnes: number | null;
  area_km2: number | null;
  start_date: string | null;
  end_date: string | null;
  geom: GeoJSON.Polygon | null;
  created_at: string;
}

/** A milestone names, up front, the satellite layer that will be used to verify it.
 *  The claim and the check are declared together — that's what stops the goalposts moving. */
export interface Milestone {
  id: string;
  initiative_id: string;
  seq: number;
  name: string;
  name_ar: string | null;
  due_date: string | null;
  metric_key: string | null;
  target_value: number | null;
  target_unit: string | null;
  verified_value: number | null;
  status: MilestoneStatus;
  verification_layer: string | null;
  verification_note: string | null;
  verified_at: string | null;
}

/** One attempt by the verification job to read the ground and judge a milestone.
 *  Recorded whether or not it changed anything — this is the evidence chain a regulator
 *  will ask to see. `decision` is never 'verified' without a real observed_value. */
export interface VerificationRun {
  id: number;
  milestone_id: string;
  initiative_id: string;
  provider: "sentinel_hub" | "copernicus" | "manual" | "none";
  layer: string | null;
  metric_key: string | null;
  observed_value: number | null;
  target_value: number | null;
  comparator: string | null;
  decision: "verified" | "failed" | "inconclusive" | "no_provider";
  reason: string;
  scene_date: string | null;
  cloud_pct: number | null;
  evidence: Record<string, unknown>;
  created_at: string;
}

export interface Disbursement {
  id: string;
  org_id: string;
  initiative_id: string;
  milestone_id: string | null;
  amount: number;
  currency: string;
  status: DisbursementStatus;
  note: string | null;
  requested_at: string;
  approved_at: string | null;
  paid_at: string | null;
}

/** Every KPI carries its provenance. A number without a source is a rumour. */
export interface Kpi {
  id: string;
  initiative_id: string;
  key: string;
  label: string;
  label_ar: string | null;
  value: number | null;
  unit: string | null;
  target: number | null;
  trend: "up" | "down" | "flat" | null;
  source_layer: string | null;
  method: string | null;
  cadence: string | null;
  confidence: number | null;
  updated_at: string;
}

export interface Layer {
  id: string;
  key: string;
  name: string;
  name_ar: string | null;
  family:
    | "basemap"
    | "optical"
    | "sar"
    | "hyperspectral"
    | "thermal"
    | "terrain"
    | "public"
    | "sovereign";
  provider: string | null;
  tile_url: string | null;
  legend: { stops?: { v: number; c: string; l: string }[] } | null;
  attribution: string | null;
  is_active: boolean;
}

export interface Poi {
  id: string;
  org_id: string;
  initiative_id: string | null;
  name: string;
  name_ar: string | null;
  poi_type: string | null;
  severity: "low" | "medium" | "high" | "critical" | null;
  status: PoiStatus;
  geom: GeoJSON.Point | null;
  evidence: Record<string, unknown>;
  created_at: string;
}

export interface Report {
  id: string;
  org_id: string;
  initiative_id: string | null;
  kind:
    | "exec_brief"
    | "technical"
    | "field"
    | "regulatory"
    | "progress"
    | "feasibility"
    | "market_entry";
  title: string;
  lang: "en" | "ar";
  content_md: string | null;
  status: "pending" | "generating" | "ready" | "failed";
  mesh_job_id: string | null;
  model: string | null;
  created_at: string;
}

/** The AOI the user has drawn. Everything in the map workspace hangs off this. */
export interface Aoi {
  geometry: GeoJSON.Polygon;
  areaKm2: number;
  bbox: [number, number, number, number];
  centroid: [number, number];
}

/** What the user currently has selected on the map — a dropped pin, a drawn fence, or an
 *  existing POI they clicked. Everything the workspace does (ask, save, report, alert) hangs
 *  off this one object. */
export interface Selection {
  kind: "point" | "area";
  /** lng, lat — the point itself, or an area's centroid. */
  lng: number;
  lat: number;
  /** Present for a ring-fence. */
  aoi?: Aoi;
  /** The mapbox-draw feature id, so the workspace can clear it after saving. */
  drawId?: string;
  /** Set when the selection is an existing POI clicked on the map. */
  existingPoi?: Poi;
}
