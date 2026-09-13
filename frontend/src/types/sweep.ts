// Fila del sweep CSV producido por eval/harness.py. Corresponde a la salida de
// eval/runs/sweep_post-roundtrip.csv (una fila por seed + fila AGG_n=N).
// La ultima columna `recall` se deriva de recall_num / recall_den (0 si den=0).

export interface SweepRow {
  seed: number;
  findings: number;
  leads: number;
  recall_num: number;
  recall_den: number;
  false_accusations: number;
  peso_error_pct: number;
  wall_clock: number;
  recall: number; // derivada: recall_num / recall_den, o 0 si recall_den es 0.
}
