/** Rótulos e datas para a lista de projetos. */

import type { VideoStatus } from "./types";

const STATUS_LABELS: Record<VideoStatus, string> = {
  pending: "Na fila",
  queued: "Na fila",
  downloading: "Baixando",
  downloaded: "Baixado",
  transcribing: "Transcrevendo",
  transcribed: "Transcrito",
  processing: "Criando clips",
  clipped: "Criando clips",
  rendered: "Renderizado",
  exporting: "Exportando",
  exported: "Concluído",
  completed: "Concluído",
  failed: "Falhou",
  cancelled: "Cancelado",
};

export function statusLabel(status: VideoStatus): string {
  return STATUS_LABELS[status] ?? status;
}

export type ProjectFilter = "all" | "processing" | "done" | "failed";

export const FILTER_OPTIONS: readonly { id: ProjectFilter; name: string }[] = [
  { id: "all", name: "Todos" },
  { id: "processing", name: "Processando" },
  { id: "done", name: "Concluídos" },
  { id: "failed", name: "Falharam" },
];

const DONE: readonly VideoStatus[] = ["rendered", "exported", "completed"];
const BROKEN: readonly VideoStatus[] = ["failed", "cancelled"];

export function matchesFilter(status: VideoStatus, filter: ProjectFilter): boolean {
  if (filter === "all") return true;
  if (filter === "done") return DONE.includes(status);
  if (filter === "failed") return BROKEN.includes(status);
  return !DONE.includes(status) && !BROKEN.includes(status);
}

function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

/** `Hoje, 17:42` / `Ontem, 22:10` / `03/09/2026`. */
export function humanDate(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";

  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");

  if (sameDay(date, now)) return `Hoje, ${hour}:${minute}`;

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameDay(date, yesterday)) return `Ontem, ${hour}:${minute}`;

  const day = String(date.getDate()).padStart(2, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  return `${day}/${month}/${date.getFullYear()}`;
}

/** `42:18` a partir de segundos; `—` quando a duração é desconhecida. */
export function formatVideoDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds) || seconds <= 0) return "—";

  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const pad = (value: number) => String(value).padStart(2, "0");

  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(secs)}` : `${pad(minutes)}:${pad(secs)}`;
}

export function matchesSearch(title: string | null, sourceUrl: string, term: string): boolean {
  const needle = term.trim().toLowerCase();
  if (!needle) return true;
  return `${title ?? ""} ${sourceUrl}`.toLowerCase().includes(needle);
}
