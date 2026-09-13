// Context + Provider + hook del estate cargado. Mismo patron que
// useSubmission.ts (createElement porque es .ts, no .tsx).
//
// useSubmission expone lo que el pipeline CONCLUYO; este expone contra que
// se puede COMPROBAR. La UI necesita los dos para que un exhibit sea
// verificable en vez de solo citable.

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { Database } from "sql.js";
import {
  clearEstateBytes,
  loadEstateBytes,
  openEstate,
  saveEstateBytes,
  summarizeEstate,
  type TableSummary,
} from "@/lib/estateStore";

export interface EstateContextValue {
  /** null = no hay estate cargado. Los exhibits no se pueden verificar. */
  db: Database | null;
  label: string | null;
  savedAt: string | null;
  tables: TableSummary[];
  totalRows: number;
  isLoading: boolean;
  error: Error | null;
  /** Adopta un estate recien construido (o un .db que el auditor abrio) y
   * lo persiste, para que sobreviva el reload que exige el flujo. */
  adoptEstate: (bytes: Uint8Array, label: string) => Promise<void>;
  forgetEstate: () => Promise<void>;
}

const EstateContext = createContext<EstateContextValue | null>(null);

export function EstateProvider({ children }: { children: ReactNode }) {
  // El Database vivo tambien en un ref: cerrarlo es un efecto secundario y
  // React StrictMode invoca DOS VECES las funciones de actualizacion de
  // estado en desarrollo. Cerrar ahi dentro cerraria una base ya cerrada.
  const dbRef = useRef<Database | null>(null);
  const [db, setDb] = useState<Database | null>(null);
  const [label, setLabel] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [tables, setTables] = useState<TableSummary[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);

  // Al montar: recupera el estate persistido, si hay.
  useEffect(() => {
    let cancelled = false;
    loadEstateBytes()
      .then(async (stored) => {
        if (cancelled || !stored) return;
        const opened = await openEstate(stored.bytes);
        if (cancelled) {
          opened.close();
          return;
        }
        dbRef.current = opened;
        setDb(opened);
        setLabel(stored.label);
        setSavedAt(stored.savedAt);
        setTables(summarizeEstate(opened));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // Un estate ilegible no debe tumbar la app: la UI sigue mostrando
        // las conclusiones, solo que sin poder comprobarlas.
        setError(err instanceof Error ? err : new Error(String(err)));
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const adoptEstate = useCallback(async (bytes: Uint8Array, nextLabel: string) => {
    setError(null);
    const opened = await openEstate(bytes);
    if (dbRef.current) dbRef.current.close();
    dbRef.current = opened;
    setDb(opened);
    setLabel(nextLabel);
    setTables(summarizeEstate(opened));
    const now = new Date().toISOString();
    setSavedAt(now);
    try {
      await saveEstateBytes(bytes, nextLabel);
    } catch (err: unknown) {
      // El estate ya esta vivo en memoria; que no se haya podido persistir
      // solo significa que no sobrevive el reload. Se dice, no se esconde.
      setError(err instanceof Error ? err : new Error(String(err)));
    }
  }, []);

  const forgetEstate = useCallback(async () => {
    if (dbRef.current) dbRef.current.close();
    dbRef.current = null;
    setDb(null);
    setLabel(null);
    setSavedAt(null);
    setTables([]);
    setError(null);
    await clearEstateBytes();
  }, []);

  const totalRows = useMemo(() => tables.reduce((s, t) => s + t.rows, 0), [tables]);

  const value: EstateContextValue = {
    db,
    label,
    savedAt,
    tables,
    totalRows,
    isLoading,
    error,
    adoptEstate,
    forgetEstate,
  };
  return createElement(EstateContext.Provider, { value }, children);
}

export function useEstate(): EstateContextValue {
  const ctx = useContext(EstateContext);
  if (ctx === null) {
    throw new Error("useEstate debe usarse dentro de <EstateProvider>.");
  }
  return ctx;
}
