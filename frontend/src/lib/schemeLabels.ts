// Human-readable labels + colors per scheme_type. Hex values must stay
// aligned with frontend/tailwind.config.ts theme.colors.scheme.*.

import { SCHEME_TYPES, type SchemeType } from "@/types/submission";

export interface SchemeLabel {
  label: string;
  short: string;
  color: string;
}

export const SCHEME_LABELS: Record<SchemeType, SchemeLabel> = {
  phantom_vendor: {
    label: "Phantom vendor",
    short: "Phantom",
    color: "#A44200",
  },
  kickback: {
    label: "Kickback (vendor → employee)",
    short: "Kickback",
    color: "#DC2626",
  },
  round_tripping: {
    label: "Round-tripping (funds cycle)",
    short: "Round-trip",
    color: "#D97706",
  },
  threshold_splitting: {
    label: "Threshold splitting",
    short: "Splitting",
    color: "#CA8A04",
  },
  revenue_inflation: {
    label: "Revenue inflation",
    short: "Revenue",
    color: "#B45309",
  },
};

export { SCHEME_TYPES };
