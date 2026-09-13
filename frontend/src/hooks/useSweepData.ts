// Carga /eval/runs/sweep_post-roundtrip.csv una sola vez y memoiza el
// resultado. Fallback silencioso al mock si el fetch falla (por ejemplo
// cuando no hay backend corriendo el sweep).

import { useEffect, useMemo, useState } from "react";
import { loadSweep } from "@/lib/loadSweep";
import { MOCK_SWEEP } from "@/mocks/sweep.mock";
import type { SweepRow } from "@/types/sweep";

export interface UseSweepDataOptions {
  url?: string;
}

export interface UseSweepDataResult {
  rows: SweepRow[];
  isMock: boolean;
  isLoading: boolean;
  error: Error | null;
}

export function useSweepData(
  options: UseSweepDataOptions = {},
): UseSweepDataResult {
  const { url = "/eval/runs/sweep_post-roundtrip.csv" } = options;
  const [rows, setRows] = useState<SweepRow[]>(MOCK_SWEEP);
  const [isMock, setIsMock] = useState<boolean>(true);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadSweep(url)
      .then((data) => {
        if (cancelled) return;
        setRows(data);
        setIsMock(false);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const asError = err instanceof Error ? err : new Error(String(err));
        setError(asError);
        setIsMock(true);
      })
      .finally(() => {
        if (cancelled) return;
        setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [url]);

  // useMemo garantiza referencia estable mientras `rows` no cambie.
  const memoRows = useMemo(() => rows, [rows]);
  return { rows: memoRows, isMock, isLoading, error };
}
