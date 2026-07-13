import { useState } from "react";

import MapView from "../components/MapView";
import AskPanel from "../components/AskPanel";
import LayerSwitcher from "../components/LayerSwitcher";
import { logAudit } from "../lib/audit";
import type { Aoi, Initiative, Layer, Poi } from "../lib/types";

export default function MapWorkspace({
  layers,
  initiatives,
  pois,
  orgId,
}: {
  layers: Layer[];
  initiatives: Initiative[];
  pois: Poi[];
  orgId: string;
}) {
  const [aoi, setAoi] = useState<Aoi | null>(null);
  const [basemapKey, setBasemapKey] = useState("esri_imagery");
  const [activeLayerKeys, setActiveLayerKeys] = useState<string[]>([]);
  const [lang, setLang] = useState<"en" | "ar">("en");

  function toggleLayer(key: string) {
    setActiveLayerKeys((prev) => {
      const on = !prev.includes(key);
      void logAudit({ orgId, action: "layer.toggle", outputs: { layer: key, on } });
      return on ? [...prev, key] : prev.filter((k) => k !== key);
    });
  }

  function handleAoi(next: Aoi | null) {
    setAoi(next);
    if (next) {
      void logAudit({
        orgId,
        action: "aoi.select",
        aoi: next,
        sourceLayers: activeLayerKeys,
        outputs: { area_km2: next.areaKm2 },
      });
    }
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
          onAoiChange={handleAoi}
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
        <button
          onClick={() => setLang((l) => (l === "en" ? "ar" : "en"))}
          className="absolute right-4 top-4 z-10 rounded-lg border border-field-line bg-field-800/90 px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-wider text-white/70 backdrop-blur transition hover:text-white"
        >
          {lang === "en" ? "عربي" : "EN"}
        </button>
      </div>

      <aside className="w-[400px] shrink-0 border-l border-line">
        <AskPanel
          aoi={aoi}
          activeLayers={activeLayerKeys}
          orgId={orgId}
          lang={lang}
        />
      </aside>
    </div>
  );
}
