// Fetch de events.jsonl como texto plano, split por linea, JSON.parse por linea.
// Sin validacion Zod: los eventos vienen del emisor propio, la union sellada
// vive en @/types/events.

import type { Event } from "@/types/events";

export async function loadEvents(url: string): Promise<Event[]> {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`loadEvents: HTTP ${res.status} para ${url}`);
  }
  const text = await res.text();
  const events: Event[] = [];
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    events.push(JSON.parse(trimmed) as Event);
  }
  return events;
}
