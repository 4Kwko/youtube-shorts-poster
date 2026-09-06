/** Fila local da Home: URLs aguardando envio. Nada aqui toca o backend. */

export const MAX_BATCH_VIDEOS = 20;

export type QueueKind = "url" | "file";

export interface QueueItem {
  id: string;
  kind: QueueKind;
  /** URL do vídeo ou caminho absoluto do arquivo. */
  value: string;
  /** O que aparece na linha da fila. */
  label: string;
}

export const VIDEO_EXTENSIONS = ["mp4", "mkv", "mov", "webm", "avi", "m4v"];

/** Nome do arquivo a partir do caminho, em Windows ou Unix. */
export function fileLabel(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

export function isValidUrl(value: string): boolean {
  try {
    const parsed = new URL(value.trim());
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

/** Separa um texto colado em URLs: quebra de linha, espaço ou tab. */
export function parseUrls(input: string): string[] {
  return input
    .split(/[\s\n\r\t]+/)
    .map((part) => part.trim())
    .filter((part) => part !== "" && isValidUrl(part));
}

export interface AddResult {
  items: QueueItem[];
  added: number;
  /** Recusadas por já estarem na fila ou por estourar o limite. */
  skipped: number;
}

/**
 * Acrescenta URLs à fila, preservando a ordem de inserção.
 *
 * Duplicata dentro da fila é ignorada; deduplicação contra o histórico não
 * existe de propósito — reprocessar um vídeo antigo é legítimo.
 */
function append(current: QueueItem[], kind: QueueKind, values: string[]): AddResult {
  if (values.length === 0) return { items: current, added: 0, skipped: 0 };

  const items = [...current];
  const seen = new Set(items.map((item) => item.value));
  let added = 0;
  let skipped = 0;

  for (const value of values) {
    // Limite e duplicata valem para a fila inteira, misturando URL e arquivo.
    if (seen.has(value) || items.length >= MAX_BATCH_VIDEOS) {
      skipped += 1;
      continue;
    }
    seen.add(value);
    items.push({
      id: `${Date.now()}-${items.length}-${value}`,
      kind,
      value,
      label: kind === "file" ? fileLabel(value) : shortenUrl(value),
    });
    added += 1;
  }

  return { items, added, skipped };
}

export function addUrls(current: QueueItem[], input: string): AddResult {
  return append(current, "url", parseUrls(input));
}

/** Caminhos vindos do seletor nativo; a validação real é do backend. */
export function addFiles(current: QueueItem[], paths: string[]): AddResult {
  return append(
    current,
    "file",
    paths.map((path) => path.trim()).filter((path) => path !== ""),
  );
}

export function partition(items: QueueItem[]): { urls: string[]; paths: string[] } {
  return {
    urls: items.filter((item) => item.kind === "url").map((item) => item.value),
    paths: items.filter((item) => item.kind === "file").map((item) => item.value),
  };
}

export function removeItem(current: QueueItem[], id: string): QueueItem[] {
  return current.filter((item) => item.id !== id);
}

/** Encurta a URL para a linha da fila. */
export function shortenUrl(url: string, max = 46): string {
  const withoutScheme = url.replace(/^https?:\/\//, "");
  if (withoutScheme.length <= max) return withoutScheme;
  return `${withoutScheme.slice(0, max - 10)}…${withoutScheme.slice(-9)}`;
}

export function submitLabel(count: number): string {
  if (count <= 1) return "Gerar projeto";
  return `Gerar ${count} projetos`;
}
