// Fetch + parse validado del submission.json contra SubmissionSchema.
// Devuelve un Submission tipado o lanza (ZodError / HTTP error).

import { SubmissionSchema, type Submission } from "@/types/submission";

export async function loadSubmission(url: string): Promise<Submission> {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`loadSubmission: HTTP ${res.status} para ${url}`);
  }
  const raw: unknown = await res.json();
  return SubmissionSchema.parse(raw);
}
