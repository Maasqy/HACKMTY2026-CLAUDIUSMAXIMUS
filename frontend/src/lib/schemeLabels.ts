// Diccionario de labels legibles y colores por scheme_type. Los hex deben
// coincidir con frontend/tailwind.config.ts theme.colors.scheme.*.

import { SCHEME_TYPES, type SchemeType } from "@/types/submission";

export interface SchemeLabel {
  label: string;
  short: string;
  color: string; // hex, alineado con tailwind.config.ts colors.scheme.*
}

export const SCHEME_LABELS: Record<SchemeType, SchemeLabel> = {
  phantom_vendor: {
    label: "Proveedor fantasma",
    short: "Fantasma",
    color: "#6366F1",
  },
  kickback: {
    label: "Retorno del proveedor (kickback)",
    short: "Kickback",
    color: "#E11D48",
  },
  round_tripping: {
    label: "Circulo de fondos",
    short: "Circulo",
    color: "#0891B2",
  },
  threshold_splitting: {
    label: "Fraccionamiento de compras",
    short: "Fraccionamiento",
    color: "#EA580C",
  },
  revenue_inflation: {
    label: "Ingreso ficticio",
    short: "Ingreso",
    color: "#059669",
  },
};

// Re-export para conveniencia de callers.
export { SCHEME_TYPES };
