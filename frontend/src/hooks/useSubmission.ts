// Context + Provider + hook para el Submission. Hace fetch a /out/submission.json
// (servido por vite via publicDir=..) y cae al mock si falla. Expone la flag
// `isMock` para que la UI muestre un banner honesto.

import {
  createContext,
  createElement,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { loadSubmission } from "@/lib/loadSubmission";
import { MOCK_SUBMISSION } from "@/mocks/submission.mock";
import type { Submission } from "@/types/submission";

export interface SubmissionContextValue {
  submission: Submission;
  isMock: boolean;
  isLoading: boolean;
  error: Error | null;
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

  useEffect(() => {
    let cancelled = false;
    loadSubmission(url)
      .then((data) => {
        if (cancelled) return;
        setSubmission(data);
        setIsMock(false);
        setError(null);
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

  const value: SubmissionContextValue = { submission, isMock, isLoading, error };
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
