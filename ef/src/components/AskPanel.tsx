import { useRef, useState } from "react";
import { AlertTriangle, MapPin, Send, Square } from "lucide-react";

import { ask, buildGeoPrompt, INFERENCE_PROVIDER, SOVEREIGN_INFERENCE } from "../lib/mesh";
import { logAudit } from "../lib/audit";
import { formatArea } from "../lib/geo";
import type { Aoi } from "../lib/types";

interface Turn {
  role: "user" | "assistant";
  text: string;
  meta?: { provider: string; latency_ms: number };
}

interface Props {
  aoi: Aoi | null;
  activeLayers: string[];
  initiativeName?: string | null;
  orgId: string | null;
  lang: "en" | "ar";
}

const SUGGESTIONS = {
  en: [
    "What's the vegetation stress across this area?",
    "Any signs of unlicensed land clearance here?",
    "Summarise water and soil conditions.",
  ],
  ar: [
    "ما هو إجهاد الغطاء النباتي في هذه المنطقة؟",
    "هل توجد مؤشرات على إزالة غير مرخصة للأراضي؟",
    "لخص أوضاع المياه والتربة.",
  ],
};

export default function AskPanel({ aoi, activeLayers, initiativeName, orgId, lang }: Props) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<(() => void) | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const scrollDown = () =>
    requestAnimationFrame(() =>
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }),
    );

  async function submit(question: string) {
    if (!question.trim() || busy) return;

    setTurns((t) => [...t, { role: "user", text: question }, { role: "assistant", text: "" }]);
    setInput("");
    setBusy(true);
    scrollDown();

    const prompt = buildGeoPrompt({ question, aoi, activeLayers, initiativeName, lang });

    if (orgId) {
      void logAudit({
        orgId,
        action: "ask.query",
        aoi,
        sourceLayers: activeLayers,
        outputs: { question, provider: INFERENCE_PROVIDER },
      });
    }

    abortRef.current = await ask(
      { message: prompt },
      {
        onToken: (text) => {
          setTurns((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last?.role === "assistant") last.text += text;
            return next;
          });
          scrollDown();
        },
        onDone: (meta) => {
          setTurns((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last?.role === "assistant") last.meta = meta;
            return next;
          });
          setBusy(false);
          scrollDown();
        },
        onError: (err) => {
          setTurns((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last?.role === "assistant") last.text = err.message;
            return next;
          });
          setBusy(false);
        },
      },
    );
  }

  return (
    <div className="flex h-full flex-col bg-field-900" dir={lang === "ar" ? "rtl" : "ltr"}>
      {/* AOI context — makes it unambiguous what the model is reasoning about. */}
      <div className="border-b border-field-line px-4 py-3">
        <div className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-signal">
          <MapPin size={11} />
          {lang === "ar" ? "منطقة الاهتمام" : "Area of interest"}
        </div>
        {aoi ? (
          <div className="mt-1.5 font-mono text-xs text-white/70">
            {aoi.centroid[1].toFixed(3)}°N, {aoi.centroid[0].toFixed(3)}°E ·{" "}
            {formatArea(aoi.areaKm2)}
            <div className="mt-1 text-white/35">
              {activeLayers.length
                ? activeLayers.join(" · ")
                : lang === "ar"
                  ? "لا توجد طبقات نشطة"
                  : "no active layers"}
            </div>
          </div>
        ) : (
          <div className="mt-1.5 text-xs text-white/35">
            {lang === "ar"
              ? "ارسم منطقة على الخريطة للبدء."
              : "Draw a region on the map to begin."}
          </div>
        )}
      </div>

      {/* Residency banner. While inference leaves the Kingdom, say so — plainly, in the
          place the analyst is actually looking. Hiding it would make the platform lie. */}
      {!SOVEREIGN_INFERENCE && (
        <div className="flex items-start gap-2 border-b border-amber-500/20 bg-amber-500/10 px-4 py-2.5">
          <AlertTriangle size={13} className="mt-0.5 shrink-0 text-amber-400" />
          <p className="text-[11px] leading-relaxed text-amber-200/90">
            {lang === "ar"
              ? "الاستدلال يعمل حالياً على مزوّد خارجي، وليس داخل المملكة. لا تُدخل بيانات مصنّفة."
              : "Inference currently runs on an external provider, not inside the Kingdom. Do not enter classified data."}
          </p>
        </div>
      )}

      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {turns.length === 0 && (
          <div className="space-y-2">
            <p className="text-sm text-white/40">
              {lang === "ar" ? "اسأل الخريطة." : "Chat directly with the map."}
            </p>
            {SUGGESTIONS[lang].map((s) => (
              <button
                key={s}
                onClick={() => submit(s)}
                className="block w-full rounded-lg border border-field-line bg-field-800 px-3 py-2 text-start text-xs text-white/55 transition hover:border-signal/40 hover:text-white/90"
              >
                {s}
              </button>
            ))}
          </div>
        )}

        {turns.map((turn, i) => (
          <div key={i}>
            {turn.role === "user" ? (
              <div className="ms-auto max-w-[85%] rounded-lg rounded-se-sm bg-signal/12 px-3 py-2 text-sm text-white/90">
                {turn.text}
              </div>
            ) : (
              <div className="max-w-[95%]">
                <div className="whitespace-pre-wrap text-sm leading-relaxed text-white/80">
                  {turn.text || (busy ? <span className="text-white/25">Thinking…</span> : null)}
                </div>

                {/* Provenance, stated accurately — whatever it happens to be. */}
                {turn.meta && (
                  <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px] text-white/35">
                    <span>served by {turn.meta.provider}</span>
                    <span>{turn.meta.latency_ms} ms</span>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="border-t border-field-line p-3">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit(input);
              }
            }}
            rows={1}
            placeholder={lang === "ar" ? "اسأل عن هذه المنطقة…" : "Ask about this area…"}
            className="max-h-32 flex-1 resize-none rounded-lg border border-field-line bg-field-800 px-3 py-2 text-sm text-white/90 outline-none transition placeholder:text-white/25 focus:border-signal/50"
          />
          {busy ? (
            <button
              onClick={() => {
                abortRef.current?.();
                setBusy(false);
              }}
              className="rounded-lg border border-field-line bg-field-800 p-2 text-white/50 transition hover:text-white"
              title="Stop"
            >
              <Square size={16} />
            </button>
          ) : (
            <button
              onClick={() => submit(input)}
              disabled={!input.trim()}
              className="rounded-lg bg-signal p-2 text-field-900 transition disabled:opacity-25"
              title="Send"
            >
              <Send size={16} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
