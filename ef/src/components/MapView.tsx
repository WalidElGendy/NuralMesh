import { useEffect, useRef, useState } from "react";
import maplibregl, { Map as MlMap } from "maplibre-gl";
import MapboxDraw from "@mapbox/mapbox-gl-draw";
import "maplibre-gl/dist/maplibre-gl.css";
import "@mapbox/mapbox-gl-draw/dist/mapbox-gl-draw.css";

import { KSA_CENTER, toAoi } from "../lib/geo";
import type { Aoi, Initiative, Layer, Poi } from "../lib/types";

const SEVERITY_COLOR: Record<string, string> = {
  critical: "#ef4444",
  high: "#f97316",
  medium: "#eab308",
  low: "#3FD68C",
};

interface Props {
  layers: Layer[];
  activeLayerKeys: string[];
  basemapKey: string;
  initiatives: Initiative[];
  pois: Poi[];
  onAoiChange: (aoi: Aoi | null) => void;
  onPoiClick?: (poi: Poi) => void;
}

export default function MapView({
  layers,
  activeLayerKeys,
  basemapKey,
  initiatives,
  pois,
  onAoiChange,
  onPoiClick,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);

  /**
   * Explicit readiness flag.
   *
   * The previous version did `isStyleLoaded() ? apply() : map.once("load", apply)`. That is a
   * race: whichever branch you take, the *other* one silently wins, and if the style reports
   * itself unloaded at the wrong moment nothing is ever added and the map just sits there
   * black with no error. Tracking readiness in state makes the apply effect re-run the moment
   * the map is genuinely usable, every time.
   */
  const [ready, setReady] = useState(false);

  const onAoiChangeRef = useRef(onAoiChange);
  onAoiChangeRef.current = onAoiChange;
  const onPoiClickRef = useRef(onPoiClick);
  onPoiClickRef.current = onPoiClick;
  const poisRef = useRef(pois);
  poisRef.current = pois;

  // ── Init map once ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      center: KSA_CENTER,
      zoom: 4.6,
      attributionControl: false,
      style: {
        version: 8,
        sources: {},
        layers: [{ id: "bg", type: "background", paint: { "background-color": "#0B0F0D" } }],
        glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
      },
    });

    // Without this, a bad tile URL or style failure is completely silent — which is exactly
    // how the map ended up black with a clean console.
    map.on("error", (e) => console.error("[EF/map]", e?.error?.message ?? e));

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

    const draw = new MapboxDraw({
      displayControlsDefault: false,
      controls: { polygon: true, trash: true },
      styles: drawStyles,
    });
    map.addControl(draw as unknown as maplibregl.IControl, "top-left");

    const syncAoi = () => {
      const poly = draw.getAll().features.find((f) => f.geometry.type === "Polygon");
      onAoiChangeRef.current(poly ? toAoi(poly.geometry as GeoJSON.Polygon) : null);
    };
    map.on("draw.create", syncAoi);
    map.on("draw.update", syncAoi);
    map.on("draw.delete", () => onAoiChangeRef.current(null));

    map.on("load", () => {
      // Vector overlays. Rasters get inserted *beneath* these later.
      map.addSource("initiatives", { type: "geojson", data: emptyFc() });
      map.addLayer({
        id: "initiatives-fill",
        type: "fill",
        source: "initiatives",
        paint: { "fill-color": "#3FD68C", "fill-opacity": 0.08 },
      });
      map.addLayer({
        id: "initiatives-line",
        type: "line",
        source: "initiatives",
        paint: { "line-color": "#3FD68C", "line-width": 1.5, "line-dasharray": [2, 1] },
      });

      map.addSource("pois", { type: "geojson", data: emptyFc() });
      map.addLayer({
        id: "pois-halo",
        type: "circle",
        source: "pois",
        paint: { "circle-radius": 12, "circle-color": ["get", "color"], "circle-opacity": 0.18 },
      });
      map.addLayer({
        id: "pois-dot",
        type: "circle",
        source: "pois",
        paint: {
          "circle-radius": 5,
          "circle-color": ["get", "color"],
          "circle-stroke-width": 1.5,
          "circle-stroke-color": "#0B0F0D",
        },
      });

      map.on("click", "pois-dot", (e) => {
        const id = e.features?.[0]?.properties?.id;
        const poi = poisRef.current.find((p) => p.id === id);
        if (poi) onPoiClickRef.current?.(poi);
      });
      map.on("mouseenter", "pois-dot", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "pois-dot", () => (map.getCanvas().style.cursor = ""));

      // Only now is it safe to add sources. This is what re-runs the raster effect.
      setReady(true);
    });

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
  }, []);

  // ── Raster stack: basemap + active analytical overlays ─────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || layers.length === 0) return;

    const instanceId = import.meta.env.VITE_SENTINEL_HUB_INSTANCE_ID as string | undefined;

    // Basemap first (bottom), then each active overlay above it.
    const wanted = [basemapKey, ...activeLayerKeys.filter((k) => k !== basemapKey)];

    // Remove rasters that are no longer wanted.
    for (const layer of layers) {
      const id = `raster-${layer.key}`;
      if (!wanted.includes(layer.key) && map.getLayer(id)) {
        map.removeLayer(id);
        if (map.getSource(id)) map.removeSource(id);
      }
    }

    for (const key of wanted) {
      const layer = layers.find((l) => l.key === key);
      if (!layer?.tile_url) continue;

      // Sentinel Hub layers need an instance ID. Skip cleanly rather than request a URL that
      // still has a literal {INSTANCE_ID} in it.
      let url = layer.tile_url;
      if (url.includes("{INSTANCE_ID}")) {
        if (!instanceId) continue;
        url = url.replace("{INSTANCE_ID}", instanceId);
      }

      const id = `raster-${layer.key}`;
      if (!map.getSource(id)) {
        map.addSource(id, {
          type: "raster",
          tiles: [url],
          tileSize: 256,
          attribution: layer.attribution ?? "",
        });
      }
      if (!map.getLayer(id)) {
        // Keep rasters beneath the vector overlays.
        const beforeId = map.getLayer("initiatives-fill") ? "initiatives-fill" : undefined;
        map.addLayer(
          {
            id,
            type: "raster",
            source: id,
            paint: { "raster-opacity": key === basemapKey ? 1 : 0.75 },
          },
          beforeId,
        );
      }
    }

    // Enforce order: basemap at the bottom of the raster stack, overlays stacked above it.
    for (const key of wanted) {
      const id = `raster-${key}`;
      if (map.getLayer(id)) {
        const beforeId = map.getLayer("initiatives-fill") ? "initiatives-fill" : undefined;
        map.moveLayer(id, beforeId);
      }
    }
  }, [ready, layers, activeLayerKeys, basemapKey]);

  // ── Initiatives + POIs ─────────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const src = map.getSource("initiatives") as maplibregl.GeoJSONSource | undefined;
    if (!src) return;
    src.setData({
      type: "FeatureCollection",
      features: initiatives
        .filter((i) => i.geom)
        .map((i) => ({
          type: "Feature" as const,
          geometry: i.geom as GeoJSON.Polygon,
          properties: { id: i.id, name: i.name, status: i.status },
        })),
    });
  }, [ready, initiatives]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const src = map.getSource("pois") as maplibregl.GeoJSONSource | undefined;
    if (!src) return;
    src.setData({
      type: "FeatureCollection",
      features: pois
        .filter((p) => p.geom)
        .map((p) => ({
          type: "Feature" as const,
          geometry: p.geom as GeoJSON.Point,
          properties: {
            id: p.id,
            name: p.name,
            color: SEVERITY_COLOR[p.severity ?? "low"] ?? "#3FD68C",
          },
        })),
    });
  }, [ready, pois]);

  return <div ref={containerRef} className="absolute inset-0" />;
}

function emptyFc(): GeoJSON.FeatureCollection {
  return { type: "FeatureCollection", features: [] };
}

/** Dark, signal-green draw styling. */
const drawStyles = [
  {
    id: "gl-draw-polygon-fill",
    type: "fill",
    filter: ["all", ["==", "$type", "Polygon"]],
    paint: { "fill-color": "#3FD68C", "fill-outline-color": "#3FD68C", "fill-opacity": 0.12 },
  },
  {
    id: "gl-draw-polygon-stroke",
    type: "line",
    filter: ["all", ["==", "$type", "Polygon"]],
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": "#3FD68C", "line-width": 2 },
  },
  {
    id: "gl-draw-vertex",
    type: "circle",
    filter: ["all", ["==", "meta", "vertex"], ["==", "$type", "Point"]],
    paint: {
      "circle-radius": 5,
      "circle-color": "#0B0F0D",
      "circle-stroke-color": "#3FD68C",
      "circle-stroke-width": 2,
    },
  },
];
