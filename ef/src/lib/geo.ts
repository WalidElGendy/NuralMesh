import area from "@turf/area";
import bbox from "@turf/bbox";
import centroid from "@turf/centroid";
import { polygon as turfPolygon } from "@turf/helpers";
import type { Aoi } from "./types";

/** Turns a drawn polygon into the AOI object the whole workspace hangs off. */
export function toAoi(geometry: GeoJSON.Polygon): Aoi {
  const feature = turfPolygon(geometry.coordinates);
  const c = centroid(feature).geometry.coordinates as [number, number];
  const b = bbox(feature) as [number, number, number, number];
  return {
    geometry,
    areaKm2: area(feature) / 1_000_000,
    bbox: b,
    centroid: c,
  };
}

/** Saudi Arabia — the default view. */
export const KSA_CENTER: [number, number] = [45.0, 24.0];
export const KSA_BOUNDS: [[number, number], [number, number]] = [
  [34.0, 16.0],
  [56.5, 32.5],
];

export function formatArea(km2: number): string {
  if (km2 < 1) return `${(km2 * 100).toFixed(0)} ha`;
  if (km2 < 1000) return `${km2.toFixed(1)} km²`;
  return `${Math.round(km2).toLocaleString()} km²`;
}
