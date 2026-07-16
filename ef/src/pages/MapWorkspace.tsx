import { useState } from "react";

import MapView from "../components/MapView";
import AskPanel from "../components/AskPanel";
import LayerSwitcher from "../components/LayerSwitcher";
import ActionCard from "../components/ActionCard";
import { useAuth, usePortfolio } from "../hooks/useEf";
import { logAudit } from "../lib/audit";
import type { Initiative, Layer, Poi, Role, Selection } from "../lib/types";

interface Props {
  layers: Layer[];
  initiatives: Initiative[];
  pois: Poi[];
  orgId: string;
  /** Optional — the workspace falls back to reading these itself, so the caller doesn't have
   *  to thread them through. That keeps App.tsx's call site unchanged. */
  role?: Role | null;
  onChanged?: () => void;
}

export default function MapWorkspace({
  layers,
  initiatives,
  pois,
  orgId,
  role: roleProp,
  onChanged: onChangedProp,
}: Props) {
  // Self-sufficient: derive role and a refetch here when the parent doesn't pass them.
  const { role: authRole } = useAuth();
  const { refresh } = usePortfolio(orgId);
  const role = roleProp ?? authRole;
  const onChanged = onChangedProp ?? refresh;

  const [selection, setSelection] = useState<Selection | null>(null);
  const [basemapKey, setBasemapKey] = useState("esri_imagery");
  const [activeLayerKeys, setActiveLayerKeys] = useState<string[]>([]);
  const [lang, setLang] = useState<"en" | "ar">("en");
  const [seed, setSeed] = useState<{ text: string; nonce: number } | null>(null);
  const [clearSignal, setClearSignal] = useState(0);

  function toggleLayer(key: string) {
    setActiveLayerKeys((prev) => {
      const on = !prev.includes(key);
      void logAudit({ orgId, action: "layer.toggle", outputs: { layer: key, on } });
      return on ? [...prev, key] : prev.filter((k) => k !== key);
    });
  }

  function handleSelect(next: Selection | null) {
    setSelection(next);
    if (next) {
      void logAudit({
        orgId,
        action: "aoi.select",
        aoi: next.aoi ?? null,
        sourceLayers: activeLayerKeys,
        outputs: { kind: next.kind, lng: next.lng, lat: next.lat },
      });
    }
  }

  function clearSelection() {
    setSelection(null);
    setClearSignal((n) => n + 1);
  }

  return (
    <div className="flex h-full">
      <div className="relative min-w-0 flex-1">
        <MapView
          layers={layers}
          activeLayerKeys={activeLayerKeys}
          basemapKey={basemapKey}
          initiatives={initiatives}
          pois={pois}
          onSelect={handleSelect}
          clearSignal={clearSignal}
        />

        <div className="absolute left-4 top-4 z-10">
          <LayerSwitcher
            layers={layers}
            basemapKey={basemapKey}
            activeLayerKeys={activeLayerKeys}
            onBasemapChange={setBasemapKey}
            onToggleLayer={toggleLayer}
          />
        </div>

        {selection && (
          <div className="absolute bottom-6 left-1/2 z-20 -translate-x-1/2">
            <ActionCard
              selection={selection}
              role={role}
              orgId={orgId}
              onAsk={(text) => setSeed({ text, nonce: Date.now() })}
              onSaved={() => {
                onChanged();
                clearSelection();
              }}
              onClose={clearSelection}
            />
          </div>
        )}

        <button
          onClick={() => setLang((l) => (l === "en" ? "ar" : "en"))}
          className="absolute right-4 top-4 z-10 rounded-lg border border-field-line bg-field-800/90 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wider text-white/70 backdrop-blur transition hover:text-white"
        >
          {lang === "en" ? "عربي" : "EN"}
        </button>
      </div>

      <aside className="w-[400px] shrink-0 border-l border-line">
        <AskPanel
          selection={selection}
          activeLayers={activeLayerKeys}
          orgId={orgId}
          lang={lang}
          seed={seed}
        />
      </aside>
    </div>
  );
}
