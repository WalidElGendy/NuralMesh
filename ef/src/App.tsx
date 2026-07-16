import Auth from "./components/Auth";
import Shell from "./components/Shell";
import Overview from "./pages/Overview";
import Initiatives from "./pages/Initiatives";
import InitiativeDetail from "./pages/InitiativeDetail";
import MapWorkspace from "./pages/MapWorkspace";
import Reports from "./pages/Reports";
import Audit from "./pages/Audit";

import { useAuth, useLayers, usePortfolio, useRoute } from "./hooks/useEf";
import { supabase } from "./lib/supabase";

export default function App() {
  const { session, orgId, role, loading } = useAuth();
  const layers = useLayers();
  const { fund, initiatives, disbursements, pois, refresh } = usePortfolio(orgId);
  const route = useRoute();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="animate-pulse font-mono text-[10px] uppercase tracking-[0.2em] text-forest-900/40">
          Establishing sovereign session…
        </div>
      </div>
    );
  }

  if (!session) return <Auth />;

  // Signed in but not a member of any org. RLS would return nothing, so be explicit
  // rather than rendering a confusingly empty dashboard.
  if (!orgId) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center px-6 text-center">
        <h1 className="font-display text-3xl">No organisation assigned</h1>
        <p className="mt-2 max-w-md text-sm leading-relaxed text-forest-900/55">
          Your account isn't a member of an EFund organisation, so there's nothing you're
          cleared to see. An administrator must add you to <code>ef.memberships</code>.
        </p>
        <button
          onClick={() => supabase.auth.signOut()}
          className="btn-ghost mt-6"
        >
          Sign out
        </button>
      </div>
    );
  }

  const email = session.user.email ?? undefined;
  const detailMatch = route.match(/^\/initiatives\/(.+)$/);
  const detail = detailMatch
    ? initiatives.find((i) => i.id === detailMatch[1]) ?? null
    : null;

  // The map takes the whole canvas; everything else lives in the padded shell.
  if (route === "/map") {
    return (
      <Shell role={role} email={email} bare>
        <MapWorkspace
          layers={layers}
          initiatives={initiatives}
          pois={pois}
          orgId={orgId}
          role={role}
          onChanged={refresh}
        />
      </Shell>
    );
  }

  return (
    <Shell role={role} email={email}>
      {detail ? (
        <InitiativeDetail
          initiative={detail}
          role={role}
          orgId={orgId}
          onChanged={refresh}
        />
      ) : route.startsWith("/initiatives") ? (
        <Initiatives initiatives={initiatives} />
      ) : route === "/reports" ? (
        <Reports orgId={orgId} initiatives={initiatives} />
      ) : route === "/audit" ? (
        <Audit role={role} />
      ) : (
        <Overview
          fund={fund}
          initiatives={initiatives}
          disbursements={disbursements}
          pois={pois}
        />
      )}
    </Shell>
  );
}
