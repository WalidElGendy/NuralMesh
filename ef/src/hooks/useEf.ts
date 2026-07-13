import { useCallback, useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";

import { supabase } from "../lib/supabase";
import type {
  Disbursement,
  Fund,
  Initiative,
  Kpi,
  Layer,
  Milestone,
  Poi,
  Report,
  Role,
} from "../lib/types";

/** Auth + the caller's org and role. RLS does the real enforcing; this only shapes the UI. */
export function useAuth() {
  const [session, setSession] = useState<Session | null>(null);
  const [orgId, setOrgId] = useState<string | null>(null);
  const [role, setRole] = useState<Role | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      if (!data.session) setLoading(false);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => {
      setSession(s);
      if (!s) setLoading(false);
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (!session) {
      setOrgId(null);
      setRole(null);
      return;
    }
    supabase
      .from("memberships")
      .select("org_id, role")
      .eq("user_id", session.user.id)
      .limit(1)
      .maybeSingle()
      .then(({ data }) => {
        setOrgId(data?.org_id ?? null);
        setRole((data?.role as Role) ?? null);
        setLoading(false);
      });
  }, [session]);

  return { session, orgId, role, loading };
}

export function useLayers() {
  const [layers, setLayers] = useState<Layer[]>([]);
  useEffect(() => {
    supabase
      .from("layers")
      .select("*")
      .eq("is_active", true)
      .then(({ data }) => setLayers((data as Layer[]) ?? []));
  }, []);
  return layers;
}

/** The whole portfolio for the caller's org. RLS scopes every one of these automatically. */
export function usePortfolio(orgId: string | null) {
  const [fund, setFund] = useState<Fund | null>(null);
  const [initiatives, setInitiatives] = useState<Initiative[]>([]);
  const [disbursements, setDisbursements] = useState<Disbursement[]>([]);
  const [pois, setPois] = useState<Poi[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!orgId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    const [f, i, d, p] = await Promise.all([
      supabase.from("funds").select("*").limit(1).maybeSingle(),
      supabase.from("initiatives").select("*").order("created_at", { ascending: false }),
      supabase.from("disbursements").select("*").order("requested_at", { ascending: false }),
      supabase.from("pois").select("*").order("created_at", { ascending: false }),
    ]);
    setFund((f.data as Fund) ?? null);
    setInitiatives((i.data as Initiative[]) ?? []);
    setDisbursements((d.data as Disbursement[]) ?? []);
    setPois((p.data as Poi[]) ?? []);
    setLoading(false);
  }, [orgId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { fund, initiatives, disbursements, pois, loading, refresh };
}

/** Everything hanging off a single initiative. */
export function useInitiativeDetail(initiativeId: string | null) {
  const [kpis, setKpis] = useState<Kpi[]>([]);
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [disbursements, setDisbursements] = useState<Disbursement[]>([]);

  const refresh = useCallback(async () => {
    if (!initiativeId) {
      setKpis([]);
      setMilestones([]);
      setDisbursements([]);
      return;
    }
    const [k, m, d] = await Promise.all([
      supabase.from("kpis").select("*").eq("initiative_id", initiativeId),
      supabase
        .from("milestones")
        .select("*")
        .eq("initiative_id", initiativeId)
        .order("seq"),
      supabase
        .from("disbursements")
        .select("*")
        .eq("initiative_id", initiativeId)
        .order("requested_at", { ascending: false }),
    ]);
    setKpis((k.data as Kpi[]) ?? []);
    setMilestones((m.data as Milestone[]) ?? []);
    setDisbursements((d.data as Disbursement[]) ?? []);
  }, [initiativeId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { kpis, milestones, disbursements, refresh };
}

export function useReports(orgId: string | null) {
  const [reports, setReports] = useState<Report[]>([]);
  const refresh = useCallback(async () => {
    if (!orgId) return;
    const { data } = await supabase
      .from("reports")
      .select("*")
      .order("created_at", { ascending: false });
    setReports((data as Report[]) ?? []);
  }, [orgId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { reports, refresh };
}

/** Minimal hash router — no dependency, no build weight. */
export function useRoute() {
  const [route, setRoute] = useState(() => window.location.hash.slice(1) || "/");
  useEffect(() => {
    const on = () => setRoute(window.location.hash.slice(1) || "/");
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export function navigate(path: string) {
  window.location.hash = path;
}
