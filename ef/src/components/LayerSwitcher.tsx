import { Layers } from "lucide-react";
import type { Layer } from "../lib/types";

const FAMILY_ABBR: Record<string, string> = {
  basemap: "base",
  optical: "opt",
  sar: "sar",
  thermal: "lst",
  hyperspectral: "hyp",
  terrain: "dsm",
  overlay: "ref",
};

interface Props {
  layers: Layer[];
  basemapKey: string;
  activeLayerKeys: string[];
  onBasemapChange: (key: string) => void;
  onToggleLayer: (key: string) => void;
}

export default function LayerSwitcher({
  layers,
  basemapKey,
  activeLayerKeys,
  onBasemapChange,
  onToggleLayer,
}: Props) {
  // Group by family, not a hardcoded key list — so new layers added to the DB show up in the
  // right section automatically. `basemap` family = exclusive radio; everything else toggles.
  const basemaps = layers.filter((l) => l.family === "basemap");
  const overlays = layers.filter((l) => l.family !== "basemap");
  const shInstance = import.meta.env.VITE_SENTINEL_HUB_INSTANCE_ID;

  return (
    <div className="max-h-[80vh] w-60 overflow-y-auto rounded-xl border border-field-line bg-field-900/92 p-3 backdrop-blur-md">
      <div className="mb-2.5 flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-white/35">
        <Layers size={11} /> Layers
      </div>

      <div className="mb-3">
        <div className="mb-1.5 font-mono text-[9px] uppercase tracking-wider text-white/25">
          Base
        </div>
        <div className="space-y-0.5">
          {basemaps.map((l) => (
            <button
              key={l.key}
              onClick={() => onBasemapChange(l.key)}
              className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition ${
                basemapKey === l.key
                  ? "bg-signal/12 text-signal"
                  : "text-white/50 hover:bg-field-800 hover:text-white/85"
              }`}
            >
              <span
                className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                  basemapKey === l.key ? "bg-signal" : "bg-white/15"
                }`}
              />
              {l.name}
            </button>
          ))}
        </div>
      </div>

      <div>
        <div className="mb-1.5 font-mono text-[9px] uppercase tracking-wider text-white/25">
          Analysis &amp; overlays
        </div>
        <div className="space-y-0.5">
          {overlays.map((l) => {
            // Sentinel Hub layers need an instance ID. Disable honestly rather than lighting
            // up a layer that renders as broken tiles.
            const needsKey = !!l.tile_url?.includes("{INSTANCE_ID}") && !shInstance;
            const active = activeLayerKeys.includes(l.key);
            return (
              <button
                key={l.key}
                disabled={needsKey}
                onClick={() => onToggleLayer(l.key)}
                title={
                  needsKey
                    ? "Set VITE_SENTINEL_HUB_INSTANCE_ID to enable this layer"
                    : (l.provider ?? undefined)
                }
                className={`flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-xs transition ${
                  needsKey
                    ? "cursor-not-allowed text-white/20"
                    : active
                      ? "bg-signal/12 text-signal"
                      : "text-white/50 hover:bg-field-800 hover:text-white/85"
                }`}
              >
                <span className="flex items-center gap-2">
                  <span
                    className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                      active ? "bg-signal" : "bg-white/15"
                    }`}
                  />
                  {l.name}
                </span>
                <span className="font-mono text-[9px] uppercase text-white/25">
                  {needsKey ? "key" : FAMILY_ABBR[l.family] ?? ""}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {activeLayerKeys.includes("ndvi") && (
        <div className="mt-3 border-t border-field-line pt-2.5">
          <div className="mb-1 font-mono text-[9px] uppercase tracking-wider text-white/25">
            NDVI
          </div>
          <div className="h-1.5 w-full rounded-full bg-gradient-to-r from-[#8c510a] via-[#f6e8c3] to-[#276419]" />
          <div className="mt-1 flex justify-between font-mono text-[9px] text-white/30">
            <span>bare soil</span>
            <span>dense veg</span>
          </div>
        </div>
      )}
    </div>
  );
}
