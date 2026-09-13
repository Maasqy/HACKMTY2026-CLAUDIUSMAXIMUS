// Reproduce events.jsonl en tiempo simulado. Speed 1 respeta los deltas t
// reales; speed>1 acelera. Delta minimo 80ms para que el ojo alcance a ver
// cada transicion incluso cuando el backend deja varios eventos con t identico.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { loadEvents } from "@/lib/loadEvents";
import { MOCK_EVENTS } from "@/mocks/events.mock";
import type { Event } from "@/types/events";

const MIN_DELAY_MS = 80;

export interface UseEventStreamOptions {
  /** URL relativa; default apunta al run seed=42. */
  url?: string;
  /** Velocidad inicial (1..20). */
  initialSpeed?: number;
}

export interface UseEventStreamResult {
  /** Eventos ya emitidos (subset de allEvents [0..cursor]). */
  events: Event[];
  /** Universo completo cargado; para saber cuando termina. */
  allEvents: Event[];
  isPlaying: boolean;
  speed: number;
  cursor: number;
  /** cursor / allEvents.length, en [0..1]. 0 si allEvents esta vacio. */
  progress: number;
  isMock: boolean;
  play: () => void;
  pause: () => void;
  reset: () => void;
  setSpeed: (speed: number) => void;
}

export function useEventStream(
  options: UseEventStreamOptions = {},
): UseEventStreamResult {
  const { url = "/out/events_0042.jsonl", initialSpeed = 4 } = options;

  const [allEvents, setAllEvents] = useState<Event[]>(MOCK_EVENTS);
  const [isMock, setIsMock] = useState<boolean>(true);
  const [cursor, setCursor] = useState<number>(0);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [speed, setSpeedState] = useState<number>(clampSpeed(initialSpeed));
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Carga inicial: intenta events.jsonl real, cae al mock.
  useEffect(() => {
    let cancelled = false;
    loadEvents(url)
      .then((data) => {
        if (cancelled) return;
        setAllEvents(data);
        setIsMock(false);
        setCursor(0);
      })
      .catch(() => {
        // Silencioso: MOCK_EVENTS ya esta en el estado.
      });
    return () => {
      cancelled = true;
    };
  }, [url]);

  const clearPending = useCallback(() => {
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  // Loop de emision: agenda el siguiente evento respecto al delta real
  // dividido por speed, con floor MIN_DELAY_MS.
  useEffect(() => {
    if (!isPlaying) {
      clearPending();
      return;
    }
    if (cursor >= allEvents.length) {
      setIsPlaying(false);
      return;
    }
    const current = allEvents[cursor];
    const previous = cursor > 0 ? allEvents[cursor - 1] : null;
    const rawDeltaSec = previous ? Math.max(0, current.t - previous.t) : 0;
    const delayMs = Math.max(MIN_DELAY_MS, (rawDeltaSec * 1000) / speed);
    timeoutRef.current = setTimeout(() => {
      setCursor((c) => c + 1);
    }, delayMs);
    return clearPending;
  }, [isPlaying, cursor, allEvents, speed, clearPending]);

  useEffect(() => clearPending, [clearPending]);

  const play = useCallback(() => {
    if (cursor >= allEvents.length) return;
    setIsPlaying(true);
  }, [cursor, allEvents.length]);

  const pause = useCallback(() => {
    setIsPlaying(false);
  }, []);

  const reset = useCallback(() => {
    clearPending();
    setIsPlaying(false);
    setCursor(0);
  }, [clearPending]);

  const setSpeed = useCallback((next: number) => {
    setSpeedState(clampSpeed(next));
  }, []);

  const events = useMemo(() => allEvents.slice(0, cursor), [allEvents, cursor]);
  const progress = allEvents.length > 0 ? cursor / allEvents.length : 0;

  return {
    events,
    allEvents,
    isPlaying,
    speed,
    cursor,
    progress,
    isMock,
    play,
    pause,
    reset,
    setSpeed,
  };
}

function clampSpeed(x: number): number {
  if (Number.isNaN(x)) return 1;
  if (x < 1) return 1;
  if (x > 20) return 20;
  return x;
}
