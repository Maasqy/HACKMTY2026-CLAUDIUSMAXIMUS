// Helper canonico de shadcn/ui: combina clsx + tailwind-merge para deduplicar
// utilidades conflictivas.

import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
