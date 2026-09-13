// Context + Provider + hook para el Submission. Hace fetch a /out/submission.json
// (servido por vite via publicDir=..) y cae al mock si falla. Expone la flag
// `isMock` para que la UI muestre un banner honesto.

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { loadSubmission } from "@/lib/loadSubmission";
import { MOCK_SUBMISSION } from "@/mocks/submission.mock";
import type { Submission } from "@/types/submission";

/** De donde salieron los datos que se estan viendo. `mock` no es un error:
 * es el estado honesto de "todavia no hay una corrida que mostrar". */
export type SubmissionSource = "mock" | "file" | "server";

export interface SubmissionContextValue {
  submission: Submission;
  isMock: boolean;
  isLoading: boolean;
  error: Error | null;
  source: SubmissionSource;
  /** Cuando se produjo lo que se esta viendo: Last-Modified del archivo, o
   * la hora en que el servidor local entrego el resultado. null = se
   * desconoce (o son datos de ejemplo). */
  producedAt: Date | null;
  /** Entrega un submission recien producido por el servidor local
   * (src/api.py) para que el dashboard lo tome sin recargar la pagina. El
   * servidor ademas lo escribe en frontend/public/out/, asi que un reload
   * despues muestra lo mismo. */
  applySubmission: (next: Submission) => void;
}

const SubmissionContext = createContext<SubmissionContextValue | null>(null);

export interface SubmissionProviderProps {
  children: ReactNode;
  /** URL relativa para fetch; default apunta al build determinista de seed=42. */
  url?: string;
}

export function SubmissionProvider({
  children,
  url = "/out/submission.json",
}: SubmissionProviderProps) {
  const [submission, setSubmission] = useState<Submission>(MOCK_SUBMISSION);
  const [isMock, setIsMock] = useState<boolean>(true);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);
  const [source, setSource] = useState<SubmissionSource>("mock");
  const [producedAt, setProducedAt] = useState<Date | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadSubmission(url)
      .then((data) => {
        if (cancelled) return;
        setSubmission(data.submission);
        setIsMock(false);
        setError(null);
        setSource("file");
        setProducedAt(data.lastModified);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // Mantiene MOCK_SUBMISSION cargado; solo registra el motivo.
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

  const applySubmission = useCallback((next: Submission) => {
    setSubmission(next);
    setIsMock(false);
    setError(null);
    setSource("server");
    setProducedAt(new Date());
  }, []);

  const value: SubmissionContextValue = {
    submission, isMock, isLoading, error, applySubmission, source, producedAt,
  };
  return createElement(SubmissionContext.Provider, { value }, children);
}

export function useSubmission(): SubmissionContextValue {
  const ctx = useContext(SubmissionContext);
  if (ctx === null) {
    throw new Error(
      "useSubmission debe usarse dentro de <SubmissionProvider>. Envolve tu <Routes> con el provider en App.tsx.",
    );
  }
  return ctx;
}
