/**
 * MeshNet client — EF's inference layer.
 *
 * EF does NOT run its own AI. Every prompt goes through the MeshNet Smart Orchestrator's
 * 7-stage pipeline (classify → cache → prune → compress → route → verify → settle) and is
 * served by a GPU provider node. That is precisely the sovereignty claim: no foreign cloud,
 * no data egress — inference executes on Saudi GPUs inside the boundary.
 *
 * The `served_by` field on the `done` event names the node that served the request, so the
 * UI can *prove* residency rather than assert it.
 */

import { getAccessToken } from "./supabase";
import type { Aoi } from "./types";

const MESH_BASE =
  (import.meta.env.VITE_MESH_API_BASE as string) ?? "https://api.beta.meshnet.co";

/** The 7 stages the orchestrator reports as it works. */
export type PipelineStage =
  | "classify"
  | "cache"
  | "prune"
  | "compress"
  | "route"
  | "verify"
  | "settle";

export interface StageEvent {
  stage: PipelineStage | string;
  message: string;
  data?: Record<string, unknown>;
}

export interface DoneEvent {
  conversation_id: string;
  message_id: string;
  /** Which GPU provider node served this — the residency proof. */
  served_by: string;
  tokens: number;
  latency_ms: number;
  model: string;
  mode: string;
}

export interface AskHandlers {
  onConversation?: (e: { conversation_id: string; title: string }) => void;
  onStage?: (e: StageEvent) => void;
  onToken?: (text: string) => void;
  onDone?: (e: DoneEvent) => void;
  onError?: (err: Error) => void;
}

/**
 * Grounds a plain-language question in the selected AOI.
 *
 * The orchestrator is a general LLM router — it has no idea what's on the map. So we hand it
 * the spatial context explicitly: where the user is looking, how big it is, which layers are
 * lit up, and what we already know about the area. Without this the model hallucinates
 * geography; with it, answers stay anchored to the ground reference.
 */
export function buildGeoPrompt(opts: {
  question: string;
  aoi: Aoi | null;
  activeLayers: string[];
  initiativeName?: string | null;
  lang: "en" | "ar";
}): string {
  const { question, aoi, activeLayers, initiativeName, lang } = opts;

  if (!aoi) {
    return lang === "ar"
      ? `${question}\n\n[السياق: لم يتم تحديد منطقة اهتمام على الخريطة بعد.]`
      : `${question}\n\n[Context: no area of interest selected on the map yet.]`;
  }

  const [minLng, minLat, maxLng, maxLat] = aoi.bbox;
  const [cLng, cLat] = aoi.centroid;

  const context = [
    `AREA OF INTEREST`,
    `- Centroid: ${cLat.toFixed(4)}°N, ${cLng.toFixed(4)}°E`,
    `- Bounding box: ${minLat.toFixed(3)}–${maxLat.toFixed(3)}°N, ${minLng.toFixed(3)}–${maxLng.toFixed(3)}°E`,
    `- Area: ${aoi.areaKm2.toFixed(1)} km²`,
    `- Active layers: ${activeLayers.length ? activeLayers.join(", ") : "none"}`,
    initiativeName ? `- Initiative: ${initiativeName}` : null,
    ``,
    `You are the analyst inside EF, a sovereign Earth-intelligence platform operating over`,
    `the Kingdom of Saudi Arabia. Answer strictly about the area above. Ground every claim in`,
    `the named layers. Where you are inferring rather than measuring, say so plainly.`,
    `If the question cannot be answered from the available layers, state what additional`,
    `capture would be required (sensor family + revisit window) instead of guessing.`,
    lang === "ar" ? `Respond in Arabic.` : `Respond in English.`,
  ]
    .filter(Boolean)
    .join("\n");

  return `${context}\n\nQUESTION\n${question}`;
}

/** Streams a grounded answer from MeshNet. Returns an abort function. */
export async function ask(
  params: {
    message: string;
    conversationId?: string | null;
    mode?: "auto" | "fast" | "deep";
  },
  handlers: AskHandlers,
): Promise<() => void> {
  const controller = new AbortController();
  const token = await getAccessToken();

  (async () => {
    try {
      const res = await fetch(`${MESH_BASE}/chat`, {
        method: "POST",
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          message: params.message,
          conversation_id: params.conversationId ?? null,
          mode: params.mode ?? "auto",
        }),
      });

      if (!res.ok || !res.body) {
        throw new Error(`MeshNet returned ${res.status} ${res.statusText}`);
      }

      // Parse the SSE frames the orchestrator emits.
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Frames are separated by a blank line.
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";

        for (const frame of frames) {
          let event = "message";
          const dataLines: string[] = [];

          for (const line of frame.split("\n")) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
          }
          if (!dataLines.length) continue;

          let payload: any;
          try {
            payload = JSON.parse(dataLines.join("\n"));
          } catch {
            continue;
          }

          switch (event) {
            case "conversation":
              handlers.onConversation?.(payload);
              break;
            case "stage":
              handlers.onStage?.(payload as StageEvent);
              break;
            case "token":
              handlers.onToken?.(payload.text ?? "");
              break;
            case "done":
              handlers.onDone?.(payload as DoneEvent);
              break;
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        handlers.onError?.(err as Error);
      }
    }
  })();

  return () => controller.abort();
}
