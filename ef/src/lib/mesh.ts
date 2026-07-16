/**
 * MeshNet inference client.
 *
 * ─────────────────────────────────────────────────────────────────────────────────────
 * READ THIS BEFORE MAKING ANY SOVEREIGNTY CLAIM IN THE UI.
 *
 * The endpoint actually deployed at api.beta.meshnet.co is `POST /api/chat` in `api.py`,
 * and it forwards the prompt to **SiliconFlow** (api.siliconflow.com, DeepSeek-V3.1) — a
 * foreign cloud inference provider. It does not route to MeshNet GPU provider nodes, it
 * does not stream, and it returns no `served_by`.
 *
 * The sovereign path — the Smart Orchestrator's 7-stage pipeline (`classify → cache →
 * prune → compress → route → verify → settle`) with SSE stage events and a `served_by`
 * naming the GPU node — lives in `smart_orchestrator/` and is NOT currently deployed
 * (Render's start command is `uvicorn api:app`).
 *
 * Until the orchestrator is deployed and routing to KSA-resident GPU nodes, this client
 * MUST NOT claim residency, and the UI must not print "no egress" or "served by a Saudi
 * GPU". Saying so while prompts egress to a Chinese API is the kind of claim that ends a
 * government engagement — and rightly.
 *
 * `SOVEREIGN_INFERENCE` below is the single switch. Flip it only when the orchestrator is
 * genuinely live, and the UI will start telling the sovereign story again.
 * ─────────────────────────────────────────────────────────────────────────────────────
 */

import { getAccessToken } from "./supabase";
import type { Selection } from "./types";

const MESH_BASE =
  (import.meta.env.VITE_MESH_API_BASE as string) ?? "https://api.beta.meshnet.co";

/** True only when api.beta.meshnet.co serves the Smart Orchestrator, not api.py. */
export const SOVEREIGN_INFERENCE = false;

/** What actually served the prompt, stated honestly. */
export const INFERENCE_PROVIDER = SOVEREIGN_INFERENCE
  ? "MeshNet GPU node · KSA"
  : "SiliconFlow · DeepSeek-V3.1 (external)";

export interface AskHandlers {
  onToken?: (text: string) => void;
  onDone?: (meta: { provider: string; latency_ms: number }) => void;
  onError?: (err: Error) => void;
}

/**
 * Grounds a plain-language question in the selected AOI.
 *
 * The model has no idea what's on the map, so we hand it the spatial context explicitly:
 * where the user is looking, how big it is, and which layers are lit. Without this it
 * hallucinates geography; with it, answers stay anchored to the ground reference.
 */
export function buildGeoPrompt(opts: {
  question: string;
  selection: Selection | null;
  activeLayers: string[];
  initiativeName?: string | null;
  lang: "en" | "ar";
}): string {
  const { question, selection, activeLayers, initiativeName, lang } = opts;

  if (!selection) {
    return lang === "ar"
      ? `${question}\n\n[السياق: لم يتم تحديد موقع على الخريطة بعد.]`
      : `${question}\n\n[Context: nothing selected on the map yet.]`;
  }

  const layersLine = `- Active layers: ${activeLayers.length ? activeLayers.join(", ") : "none"}`;

  const header =
    selection.kind === "area" && selection.aoi
      ? (() => {
          const [minLng, minLat, maxLng, maxLat] = selection.aoi!.bbox;
          return [
            `AREA OF INTEREST`,
            `- Centroid: ${selection.lat.toFixed(4)}°N, ${selection.lng.toFixed(4)}°E`,
            `- Bounding box: ${minLat.toFixed(3)}–${maxLat.toFixed(3)}°N, ${minLng.toFixed(3)}–${maxLng.toFixed(3)}°E`,
            `- Area: ${selection.aoi!.areaKm2.toFixed(1)} km²`,
            layersLine,
          ];
        })()
      : [
          `LOCATION OF INTEREST (dropped pin)`,
          `- Coordinates: ${selection.lat.toFixed(4)}°N, ${selection.lng.toFixed(4)}°E`,
          selection.existingPoi ? `- Existing POI: ${selection.existingPoi.name}` : null,
          layersLine,
        ];

  return [
    ...header.filter(Boolean),
    initiativeName ? `- Initiative: ${initiativeName}` : null,
    ``,
    `You are the analyst inside EFund, an Earth-intelligence platform operating over the`,
    `Kingdom of Saudi Arabia. Answer strictly about the area above. Ground every claim in`,
    `the named layers. Where you are inferring rather than measuring, say so plainly. If`,
    `the question cannot be answered from the available layers, state what additional`,
    `capture would be required (sensor family + revisit window) instead of guessing.`,
    lang === "ar" ? `Respond in Arabic.` : `Respond in English.`,
    ``,
    `QUESTION`,
    question,
  ]
    .filter(Boolean)
    .join("\n");
}

/**
 * Ask a grounded question.
 *
 * The deployed endpoint is non-streaming, so there are no real tokens to stream. We hand
 * the whole answer to `onToken` once — rather than fake a typewriter effect, which would
 * only be theatre pretending to be a pipeline that isn't running.
 */
export async function ask(
  params: { message: string; conversationId?: string | null },
  handlers: AskHandlers,
): Promise<() => void> {
  const controller = new AbortController();
  const token = await getAccessToken();
  const started = performance.now();

  (async () => {
    try {
      const res = await fetch(`${MESH_BASE}/api/chat`, {
        method: "POST",
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          messages: [{ role: "user", content: params.message }],
          stream: false,
        }),
      });

      if (!res.ok) {
        // 503 chat_not_configured means SILICONFLOW_API_KEY isn't set on the API.
        const detail = await res.text().catch(() => "");
        throw new Error(
          res.status === 503
            ? "Inference is not configured on the API (no provider key set)."
            : `Inference failed (${res.status}). ${detail.slice(0, 140)}`,
        );
      }

      const data = (await res.json()) as { answer?: string };
      if (!data.answer) throw new Error("The model returned an empty answer.");

      handlers.onToken?.(data.answer);
      handlers.onDone?.({
        provider: INFERENCE_PROVIDER,
        latency_ms: Math.round(performance.now() - started),
      });
    } catch (err) {
      if ((err as Error).name !== "AbortError") handlers.onError?.(err as Error);
    }
  })();

  return () => controller.abort();
}
