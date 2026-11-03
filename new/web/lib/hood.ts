// "Under the hood": turns one turn's audit trace into a timeline of what ran, which engine ran it, and how long it took.
// Pure and unit-tested; the Playground draws it. Steps with `meta: true` are calls to Meta models; the rest are our own code.
import { titleCase } from "./format.ts";
import type { IconName } from "../components/icons";
import type { AuditEvent } from "./types";

export type HoodStep = { key: string; icon: IconName; label: string; detail?: string; engine: string; meta: boolean; ms: number | null };
export type HoodSummary = { steps: HoodStep[]; metaCalls: number; metaMs: number; totalMs: number };

const MODELS: Record<string, string> = {
  "muse-spark-1.3": "Muse Spark",
  "muse-voice-transcribe-1.0": "Muse Voice Transcribe",
  "muse-image-1.0": "Muse Image",
};
export const modelLabel = (name: unknown, fallback: string) => (typeof name === "string" && name ? MODELS[name] ?? name : fallback);

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? Math.max(0, Math.round(v)) : null);

export function underTheHood(events: AuditEvent[]): HoodSummary {
  const steps: HoodStep[] = [];
  let preMs = 0;     // voice and photo happen before the sales turn starts, so they are not inside its total
  let turnMs: number | null = null;
  for (const e of events) {
    const v = e as Record<string, unknown>;
    switch (e.kind) {
      case "voice_transcribed":
        steps.push({ key: "voice", icon: "mic", label: "Listened to the voice note", detail: `${num(v.chars) ?? 0} characters heard`, engine: modelLabel(v.model, "Muse Voice Transcribe"), meta: true, ms: num(v.ms) });
        preMs += num(v.ms) ?? 0;
        break;
      case "photo_read": {
        const what = v.sku ? `Matched catalogue item ${String(v.sku)}` : v.photo === "payment_receipt" ? "Looks like a payment screenshot" : "No catalogue match";
        steps.push({ key: "photo", icon: "camera", label: "Looked at the photo", detail: what, engine: `${modelLabel(v.model, "Muse Spark")} vision`, meta: true, ms: num(v.ms) });
        preMs += num(v.ms) ?? 0;
        break;
      }
      case "analysis": {
        const llm = String(v.source ?? "").includes("llm");
        steps.push({ key: "analysis", icon: "ear", label: "Read the message", detail: `${titleCase(String(v.register ?? ""))} style`, engine: llm ? "Muse Spark + rules" : "Rules only", meta: llm, ms: num(v.ms) });
        break;
      }
      case "lead":
        steps.push({ key: "lead", icon: "trend", label: "Updated the lead", detail: `${titleCase(String(v.stage ?? ""))} · score ${String(v.score ?? "")}`, engine: "Our code", meta: false, ms: null });
        break;
      case "fraud":
        steps.push({ key: "fraud", icon: "shield", label: "Checked for fraud", detail: `${titleCase(String(v.risk ?? ""))} risk`, engine: "Our code", meta: false, ms: null });
        break;
      case "model_plan":
        steps.push({ key: "plan", icon: "brain", label: "Drafted the reply", detail: v.note ? String(v.note) : undefined, engine: modelLabel(v.model, "Language model"), meta: String(v.model ?? "").startsWith("muse"), ms: num(v.ms) });
        break;
      case "tool_call":
        steps.push({ key: `tool-${steps.length}`, icon: "wrench", label: `Ran ${titleCase(String(v.tool ?? "a tool"))}`, detail: titleCase(String(v.status ?? "")), engine: "Policy engine (our code)", meta: false, ms: null });
        break;
      case "reply_retry":
      case "reply_blocked":
        steps.push({ key: e.kind, icon: e.kind === "reply_blocked" ? "ban" : "pencil", label: e.kind === "reply_blocked" ? "Safety check blocked the draft" : "Safety check rewrote the draft", engine: "Our code", meta: false, ms: null });
        break;
      case "reply_sent":
        turnMs = num(v.total_ms);
        steps.push({ key: "sent", icon: "chat", label: v.escalated ? "Sent the reply and flagged it for you" : "Sent the reply", engine: "Our code", meta: false, ms: null });
        break;
      default:
        break;
    }
  }
  const metaSteps = steps.filter((s) => s.meta);
  return { steps, metaCalls: metaSteps.length, metaMs: metaSteps.reduce((t, s) => t + (s.ms ?? 0), 0), totalMs: preMs + (turnMs ?? 0) };
}
