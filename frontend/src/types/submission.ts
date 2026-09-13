// Zod schemas y tipos derivados para el submission oficial de Infosys.
// La forma canonica esta en docs/spec/submission_schema.json; aca vive el
// mirror TypeScript que consume el frontend.

import { z } from "zod";

// Enums cerrados — cualquier cambio requiere actualizar la spec de Infosys.
export const SOURCE_TABLES = [
  "ledger",
  "invoices",
  "bank_txns",
  "vendors",
  "efos_list",
  "purchase_orders",
  "contracts",
  "employees",
] as const;

export const SCHEME_TYPES = [
  "phantom_vendor",
  "kickback",
  "round_tripping",
  "threshold_splitting",
  "revenue_inflation",
] as const;

export const CONFIDENCE_VALUES = ["proven", "probable"] as const;

export const CLOSED_BY_VALUES = ["investigator", "challenger", "validator"] as const;

export const SourceTableSchema = z.enum(SOURCE_TABLES);
export const SchemeTypeSchema = z.enum(SCHEME_TYPES);
export const ConfidenceSchema = z.enum(CONFIDENCE_VALUES);
export const ClosedBySchema = z.enum(CLOSED_BY_VALUES);

// Un exhibit apunta a un record del estate: (source_table, record_id) es
// suficiente para que un juez lo verifique con una consulta.
export const ExhibitSchema = z.object({
  exhibit_id: z.string().min(1),
  source_table: SourceTableSchema,
  record_id: z.string().min(1),
  note: z.string(),
});

// Un paso del money trail: quien pago a quien, cuanto y bajo que exhibit.
export const MoneyTrailStepSchema = z.object({
  from: z.string().min(1),
  to: z.string().min(1),
  amount: z.number(),
  date: z.string().min(1),
  exhibit_id: z.string().min(1),
});

// Finding = acusacion validada. Requisitos duros:
// * >= 3 exhibits (invariante 2 en CLAUDE.md)
// * >= 1 entidad
// * peso_amount reconcilia con evidencia (verificado en backend)
export const FindingSchema = z.object({
  scheme_type: SchemeTypeSchema,
  entities: z.array(z.string().min(1)).min(1),
  narrative: z.string(),
  rule_broken: z.string(),
  peso_amount: z.number(),
  exhibits: z.array(ExhibitSchema).min(3),
  money_trail: z.array(MoneyTrailStepSchema),
  confidence: ConfidenceSchema,
});

// Un lead descartado: entidad, señal que la levanto y por que se cerro.
export const LeadNotPursuedSchema = z.object({
  entity: z.string().min(1),
  signal: z.string().min(1),
  reason: z.string(),
  tool_calls_made: z.array(z.string()),
  closed_by: ClosedBySchema,
});

// run_metadata: los tres numeros obligatorios + opcionales.
export const RunMetadataSchema = z.object({
  llm_calls: z.number().int().nonnegative(),
  mxn_cost: z.number().nonnegative(),
  wall_clock_seconds: z.number().nonnegative(),
  cost_by_role: z.record(z.string(), z.number()).optional(),
  deterministic: z.boolean().optional(),
});

export const SubmissionSchema = z.object({
  seed: z.number().int(),
  findings: z.array(FindingSchema),
  leads_not_pursued: z.array(LeadNotPursuedSchema),
  run_metadata: RunMetadataSchema,
});

export type SourceTable = z.infer<typeof SourceTableSchema>;
export type SchemeType = z.infer<typeof SchemeTypeSchema>;
export type Confidence = z.infer<typeof ConfidenceSchema>;
export type ClosedBy = z.infer<typeof ClosedBySchema>;
export type Exhibit = z.infer<typeof ExhibitSchema>;
export type MoneyTrailStep = z.infer<typeof MoneyTrailStepSchema>;
export type Finding = z.infer<typeof FindingSchema>;
export type LeadNotPursued = z.infer<typeof LeadNotPursuedSchema>;
export type RunMetadata = z.infer<typeof RunMetadataSchema>;
export type Submission = z.infer<typeof SubmissionSchema>;
