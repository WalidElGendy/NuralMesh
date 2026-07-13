import { useEffect, useRef } from "react";
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
  const drawRef = useRef<MapboxDraw | null>(null);
  const onAoiChangeRef = useRef(onAoiChange);
  onAoiChangeRef.current = onAoiChange;

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
        layers: [
          { id: "bg", type: "background", paint: { "background-color": "#0A0C0E" } },
        ],
        glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
      },
    });

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
    map.addControl(
      new maplibregl.AttributionControl({ compact: true }),
      "bottom-right",
    );

    // AOI drawing — polygon + rectangle, the "select a region" motion from the brief.
    const draw = new MapboxDraw({
      displayControlsDefault: false,
      controls: { polygon: true, trash: true },
      styles: drawStyles,
    });
    // MapboxDraw expects a couple of Mapbox-only internals; MapLibre needs the shim.
    map.addControl(draw as unknown as maplibregl.IControl, "top-left");

    const syncAoi = () => {
      const fc = draw.getAll();
      const poly = fc.features.find((f) => f.geometry.type === "Polygon");
      onAoiChangeRef.current(
        poly ? toAoi(poly.geometry as GeoJSON.Polygon) : null,
      );
    };

    map.on("draw.create", syncAoi);
    map.on("draw.update", syncAoi);
    map.on("draw.delete", () => onAoiChangeRef.current(null));

    map.on("load", () => {
      // Vector overlays sit above the raster stack.
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
        paint: {
          "circle-radius": 12,
          "circle-color": ["get", "color"],
          "circle-opacity": 0.18,
        },
      });
      map.addLayer({
        id: "pois-dot",
        type: "circle",
        source: "pois",
        paint: {
          "circle-radius": 5,
          "circle-color": ["get", "color"],
          "circle-stroke-width": 1.5,
          "circle-stroke-color": "#0A0C0E",
        },
      });

      map.on("click", "pois-dot", (e) => {
        const f = e.features?.[0];
        if (!f) return;
        const poi = pois.find((p) => p.id === f.properties?.id);
        if (poi) onPoiClick?.(poi);
      });
      map.on("mouseenter", "pois-dot", () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", "pois-dot", () => (map.getCanvas().style.cursor = ""));
    });

    mapRef.current = map;
    drawRef.current = draw;

    return () => {
      map.remove();
      mapRef.current = null;
      drawRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Raster stack: basemap + active analytical layers ───────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const apply = () => {
      const instanceId = import.meta.env.VITE_SENTINEL_HUB_INSTANCE_ID as string | undefined;

      // Render order: basemap first, then each active overlay on top of it.
      const wanted = [basemapKey, ...activeLayerKeys.filter((k) => k !== basemapKey)];

      // Drop raster layers that are no longer wanted.
      for (const layer of layers) {
        const id = `raster-${layer.key}`;
        if (!wanted.includes(layer.key) && map.getLayer(id)) {
          map.removeLayer(id);
          map.removeSource(id);
        }
      }

      for (const key of wanted) {
        const layer = layers.find((l) => l.key === key);
        if (!layer?.tile_url) continue;

        // Sentinel Hub layers need an instance ID; skip them cleanly if it isn't configured.
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
          map.addLayer(
            {
              id,
              type: "raster",
              source: id,
              paint: {
                // The basemap is opaque; analytical overlays blend over it.
                "raster-opacity": key === basemapKey ? 1 : 0.75,
              },
            },
            // Always keep raster beneath the vector overlays.
            map.getLayer("initiatives-fill") ? "initiatives-fill" : undefined,
          );
        }
      }
    };

    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [layers, activeLayerKeys, basemapKey]);

  // ── Push initiatives + POIs into their sources ─────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    const src = map?.getSource("initiatives") as maplibregl.GeoJSONSource | undefined;
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
  }, [initiatives]);

  useEffect(() => {
    const map = mapRef.current;
    const src = map?.getSource("pois") as maplibregl.GeoJSONSource | undefined;
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
  }, [pois]);

  return <div ref={containerRef} className="absolute inset-0" />;
}

function emptyFc(): GeoJSON.FeatureCollection {
  return { type: "FeatureCollection", features: [] };
}

/** Dark, signal-green draw styling to match the brief. */
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
      "circle-color": "#0A0C0E",
      "circle-stroke-color": "#3FD68C",
      "circle-stroke-width": 2,
    },
  },
];
