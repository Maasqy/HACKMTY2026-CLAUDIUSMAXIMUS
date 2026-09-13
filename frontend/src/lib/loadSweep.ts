// Parseo del sweep CSV con papaparse. Descarta la fila AGG_n=N (no es una
// corrida real) y agrega la columna derivada `recall`.

import Papa from "papaparse";
import type { SweepRow } from "@/types/sweep";

interface RawSweepRow {
  seed: number | string;
  findings: number;
  leads: number;
  recall_num: number;
  recall_den: number;
  false_accusations: number;
  peso_error_pct: number;
  wall_clock: number;
}

export async function loadSweep(url: string): Promise<SweepRow[]> {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`loadSweep: HTTP ${res.status} para ${url}`);
  }
  const text = await res.text();
  const parsed = Papa.parse<RawSweepRow>(text, {
    header: true,
    dynamicTyping: true,
    skipEmptyLines: true,
  });
  const rows: SweepRow[] = [];
  for (const raw of parsed.data) {
    // Descarta la fila agregada AGG_n=50 (seed vendra como string).
    if (typeof raw.seed !== "number" || Number.isNaN(raw.seed)) continue;
    const recall = raw.recall_den > 0 ? raw.recall_num / raw.recall_den : 0;
    rows.push({
      seed: raw.seed,
      findings: raw.findings,
      leads: raw.leads,
      recall_num: raw.recall_num,
      recall_den: raw.recall_den,
      false_accusations: raw.false_accusations,
      peso_error_pct: raw.peso_error_pct,
      wall_clock: raw.wall_clock,
      recall,
    });
  }
  return rows;
}
