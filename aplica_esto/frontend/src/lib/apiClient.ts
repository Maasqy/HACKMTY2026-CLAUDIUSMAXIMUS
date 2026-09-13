// Cliente del servidor local (src/api.py).
//
// El servidor es OPCIONAL: sin el, el frontend sigue funcionando como
// siempre — lee frontend/public/out/submission.json y tu corres el pipeline
// por terminal. Con el, subir el estate e investigarlo es un solo flujo.
// Por eso todo aqui falla suave: si no hay servidor, la UI lo dice y
// ofrece el camino de la terminal, no se rompe.

import type { Submission } from "@/types/submission";

// El puerto default de `python3 -m src.api`. Se puede apuntar a otro con
// VITE_API_URL para no tener que tocar codigo.
const API_BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "")
  ?? "http://127.0.0.1:8000";

export interface HealthInfo {
  ok: boolean;
  model: string;
  base_url: string;
  ollama_reachable: boolean;
  model_installed: boolean;
  models_installed: string[];
  detail: string;
}

export interface JobStatus {
  job_id: string;
  status: "running" | "done" | "error";
  progress: string[];
  progress_total: number;
  elapsed_seconds: number;
  submission: Submission | null;
  error: string | null;
}

export interface InvestigateOptions {
  maxLeads?: number;
  sinModelo?: boolean;
  offline?: boolean;
}

/** ¿Hay servidor, y esta Ollama listo? null = no hay servidor corriendo. */
export async function fetchHealth(signal?: AbortSignal): Promise<HealthInfo | null> {
  try {
    const res = await fetch(`${API_BASE}/api/health`, { signal });
    if (!res.ok) return null;
    return (await res.json()) as HealthInfo;
  } catch {
    // Servidor apagado. No es un error del usuario: es el modo por default.
    return null;
  }
}

/** Arranca la investigacion. El cuerpo es el .db crudo — sin multipart, que
 * es lo que deja al servidor sin dependencias. */
export async function startInvestigation(
  estateBytes: Uint8Array,
  opts: InvestigateOptions = {},
): Promise<string> {
  const params = new URLSearchParams({
    max_leads: String(opts.maxLeads ?? 4),
    sin_modelo: opts.sinModelo ? "1" : "0",
    offline: opts.offline ? "1" : "0",
  });
  const res = await fetch(`${API_BASE}/api/investigate?${params.toString()}`, {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream" },
    body: estateBytes as BodyInit,
  });
  if (!res.ok) {
    const detail = await res.json().then((d: { error?: string }) => d.error).catch(() => null);
    throw new Error(detail ?? `El servidor respondio ${res.status}`);
  }
  const data = (await res.json()) as { job_id: string };
  return data.job_id;
}

export async function fetchJob(jobId: string, desde = 0): Promise<JobStatus> {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}?desde=${desde}`);
  if (!res.ok) {
    const detail = await res.json().then((d: { error?: string }) => d.error).catch(() => null);
    throw new Error(detail ?? `El servidor respondio ${res.status}`);
  }
  return (await res.json()) as JobStatus;
}

/** Sondea hasta que el trabajo termina, entregando cada linea nueva de
 * progreso conforme aparece.
 *
 * Se sondea en vez de hacer streaming a proposito: el pipeline ya escribe
 * su progreso linea por linea (el mismo `on_progress` que usa la terminal),
 * y un GET por segundo contra localhost no le cuesta nada a nadie. */
export async function followJob(
  jobId: string,
  onProgress: (lines: string[]) => void,
  intervalMs = 1000,
): Promise<JobStatus> {
  let seen = 0;
  for (;;) {
    const status = await fetchJob(jobId, seen);
    if (status.progress.length > 0) {
      seen = status.progress_total;
      onProgress(status.progress);
    }
    if (status.status !== "running") return status;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}
