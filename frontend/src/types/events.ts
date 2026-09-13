// Discriminated union SELLADA de eventos emitidos por src/metrics/events.py.
// Los 10 types son cerrados; el frontend nunca inventa uno nuevo.
// Los payloads reflejan la forma real observada en out/events_0042.jsonl.

import type { Finding } from "@/types/submission";

// Base comun a todos los eventos.
export interface BaseEvent {
  seq: number;
  t: number;
  entity: string;
}

// ---------- run_started ----------
// payload: {seed, estate}
export interface RunStartedEvent extends BaseEvent {
  type: "run_started";
  payload: {
    seed: number;
    estate: string;
  };
}

// ---------- lead_opened ----------
// payload: {signal, detector, monto_estimado, reason}
export interface LeadOpenedEvent extends BaseEvent {
  type: "lead_opened";
  payload: {
    signal: string;
    detector: string;
    monto_estimado: number;
    reason: string;
  };
}

// ---------- hypothesis ----------
// El investigador propone una hipotesis testeable sobre un lead.
// TODO: no aparece en events_0042.jsonl (baseline determinista). Shape
// asumido segun docs/spec/case_file_structure.md y src/forensic/*.
export interface HypothesisEvent extends BaseEvent {
  type: "hypothesis";
  payload: {
    lead_entity: string;
    statement: string;
    scheme_type?: string;
  };
}

// ---------- tool_call ----------
// Consulta tipada al estate. args tipico incluye rfc, month, thresholds.
export interface ToolCallEvent extends BaseEvent {
  type: "tool_call";
  payload: {
    tool: string;
    args: Record<string, unknown>;
    result_summary?: string;
  };
}

// ---------- evidence ----------
// Un exhibit citable devuelto por un tool_call, listo para adjuntarse al finding.
export interface EvidenceEvent extends BaseEvent {
  type: "evidence";
  payload: {
    source_table: string;
    record_id: string;
    note: string;
    supports?: string;
  };
}

// ---------- challenge ----------
// El challenger objeta una hipotesis o exhibit. El loop debe responderlo antes
// de emitir finding.
export interface ChallengeEvent extends BaseEvent {
  type: "challenge";
  payload: {
    target: string;
    objection: string;
    resolved?: boolean;
  };
}

// ---------- lead_closed ----------
// payload: {closed_by, reason}
export interface LeadClosedEvent extends BaseEvent {
  type: "lead_closed";
  payload: {
    closed_by: "investigator" | "challenger" | "validator";
    reason: string;
  };
}

// ---------- finding ----------
// Un finding validado; payload es el mismo shape que Submission.findings[i].
export interface FindingEvent extends BaseEvent {
  type: "finding";
  payload: Finding;
}

// ---------- metrics ----------
// Snapshot de los tres numeros obligatorios. Emitido al menos una vez al final.
export interface MetricsEvent extends BaseEvent {
  type: "metrics";
  payload: {
    llm_calls?: number;
    mxn_cost?: number;
    wall_clock_seconds?: number;
    cost_by_role?: Record<string, number>;
    deterministic?: boolean;
    company_rfc?: string;
    company_clabe?: string;
    // Metrics tempranas traen contexto del estate; las finales, contadores.
    [key: string]: unknown;
  };
}

// ---------- run_finished ----------
// payload: {findings, leads_not_pursued}
export interface RunFinishedEvent extends BaseEvent {
  type: "run_finished";
  payload: {
    findings: number;
    leads_not_pursued: number;
  };
}

// Union sellada. Cualquier evento nuevo requiere que el backend (events.py)
// agregue el type al enum _ALLOWED_TYPES y aca se agregue una interface.
export type Event =
  | RunStartedEvent
  | LeadOpenedEvent
  | HypothesisEvent
  | ToolCallEvent
  | EvidenceEvent
  | ChallengeEvent
  | LeadClosedEvent
  | FindingEvent
  | MetricsEvent
  | RunFinishedEvent;

export type EventType = Event["type"];

export const EVENT_TYPES: readonly EventType[] = [
  "run_started",
  "lead_opened",
  "hypothesis",
  "tool_call",
  "evidence",
  "challenge",
  "lead_closed",
  "finding",
  "metrics",
  "run_finished",
] as const;
