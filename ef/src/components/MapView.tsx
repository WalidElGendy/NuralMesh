import { useEffect, useRef, useState } from "react";
import maplibregl, { Map as MlMap } from "maplibre-gl";
import MapboxDraw from "@mapbox/mapbox-gl-draw";
import "maplibre-gl/dist/maplibre-gl.css";
import "@mapbox/mapbox-gl-draw/dist/mapbox-gl-draw.css";

import { KSA_CENTER, toAoi } from "../lib/geo";
import type { Initiative, Layer, Poi, Selection } from "../lib/types";

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
  onSelect: (selection: Selection | null) => void;
  /** Bump to clear any drawn pin/fence (e.g. after it's been saved). */
  clearSignal: number;
}

export default function MapView({
  layers,
  activeLayerKeys,
  basemapKey,
  initiatives,
  pois,
  onSelect,
  clearSignal,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const drawRef = useRef<MapboxDraw | null>(null);

  // Explicit readiness — the isStyleLoaded() race left the map black with no error.
  const [ready, setReady] = useState(false);

  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const poisRef = useRef(pois);
  poisRef.current = pois;

  // ── Init once ──────────────────────────────────────────────────────────────
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

    map.on("error", (e) => console.error("[EF/map]", e?.error?.message ?? e));

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

    // Pin (point) + ring-fence (polygon) + trash.
    const draw = new MapboxDraw({
      displayControlsDefault: false,
      controls: { point: true, polygon: true, trash: true },
      styles: drawStyles,
    });
    map.addControl(draw as unknown as maplibregl.IControl, "top-left");
    drawRef.current = draw;

    const syncSelection = () => {
      const feats = draw.getAll().features;
      const poly = feats.find((f) => f.geometry.type === "Polygon");
      if (poly) {
        const aoi = toAoi(poly.geometry as GeoJSON.Polygon);
        onSelectRef.current({
          kind: "area",
          lng: aoi.centroid[0],
          lat: aoi.centroid[1],
          aoi,
          drawId: String(poly.id),
        });
        return;
      }
      const pt = feats.find((f) => f.geometry.type === "Point");
      if (pt) {
        const [lng, lat] = (pt.geometry as GeoJSON.Point).coordinates;
        onSelectRef.current({ kind: "point", lng, lat, drawId: String(pt.id) });
        return;
      }
      onSelectRef.current(null);
    };
    map.on("draw.create", syncSelection);
    map.on("draw.update", syncSelection);
    map.on("draw.delete", () => onSelectRef.current(null));

    map.on("load", () => {
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

      // Clicking an existing POI selects it — so the action panel and chat can act on it.
      map.on("click", "pois-dot", (e) => {
        const f = e.features?.[0];
        if (!f) return;
        const id = f.properties?.id;
        const poi = poisRef.current.find((p) => p.id === id);
        const [lng, lat] = (f.geometry as GeoJSON.Point).coordinates;
        onSelectRef.current({ kind: "point", lng, lat, existingPoi: poi });
      });
      map.on("mouseenter", "pois-dot", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "pois-dot", () => (map.getCanvas().style.cursor = ""));

      setReady(true);
    });

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
      drawRef.current = null;
      setReady(false);
    };
  }, []);

  // ── Clear drawn selection on demand ────────────────────────────────────────
  useEffect(() => {
    if (clearSignal === 0) return;
    drawRef.current?.deleteAll();
    onSelectRef.current(null);
  }, [clearSignal]);

  // ── Raster stack ───────────────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || layers.length === 0) return;

    const instanceId = import.meta.env.VITE_SENTINEL_HUB_INSTANCE_ID as string | undefined;
    const gibsDate = new Date(Date.now() - 864e5).toISOString().slice(0, 10);
    const wanted = [basemapKey, ...activeLayerKeys.filter((k) => k !== basemapKey)];

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

      let url = layer.tile_url;
      if (url.includes("{INSTANCE_ID}")) {
        if (!instanceId) continue;
        url = url.replace("{INSTANCE_ID}", instanceId);
      }
      if (url.includes("{DATE}")) url = url.replace("{DATE}", gibsDate);

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
    id: "gl-draw-point",
    type: "circle",
    filter: ["all", ["==", "$type", "Point"], ["==", "meta", "feature"]],
    paint: {
      "circle-radius": 6,
      "circle-color": "#3FD68C",
      "circle-stroke-color": "#0B0F0D",
      "circle-stroke-width": 2,
    },
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
