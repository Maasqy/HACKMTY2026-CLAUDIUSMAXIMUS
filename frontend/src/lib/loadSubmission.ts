// Fetch + parse validado del submission.json contra SubmissionSchema.
// Devuelve un Submission tipado o lanza (ZodError / HTTP error).

import { SubmissionSchema, type Submission } from "@/types/submission";

export interface LoadedSubmission {
  submission: Submission;
  /** Cabecera Last-Modified del archivo, si el servidor la manda.
   *
   * Responde "¿esto es de la corrida que acabo de hacer o de la anterior?"
   * sin meter una marca de tiempo DENTRO del submission: eso romperia la
   * promesa de que la misma estate produce el mismo archivo byte por byte,
   * que es justo lo que lo hace auditable. La frescura es metadato del
   * transporte, no del expediente. */
  lastModified: Date | null;
}

export async function loadSubmission(url: string): Promise<LoadedSubmission> {
  // `no-store`: sin esto el navegador puede servir una copia cacheada del
  // JSON aunque el pipeline ya lo haya reescrito en disco. El sintoma es
  // exactamente "corri el pipeline y la pantalla sigue igual", que manda a
  // buscar el bug al lugar equivocado.
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`loadSubmission: HTTP ${res.status} para ${url}`);
  }
  const raw: unknown = await res.json();
  const header = res.headers.get("last-modified");
  const parsed = header ? new Date(header) : null;
  return {
    submission: SubmissionSchema.parse(raw),
    lastModified: parsed && !Number.isNaN(parsed.getTime()) ? parsed : null,
  };
}
