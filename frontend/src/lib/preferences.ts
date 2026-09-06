/**
 * Preferências do app: os valores que a aba Configurações edita.
 *
 * Vivem em `localStorage` (por máquina, sem banco e sem plugin extra). São os
 * defaults da próxima geração de clips; ao clicar em Gerar clips, um snapshot
 * vai no POST e o `VideoSettings` daquele vídeo não muda mais.
 */

import { isTauri } from "./download";
import { VIDEO_EXTENSIONS } from "./queue";
import { DEFAULT_SETTINGS, normalizeSettings } from "./settings";
import type { VideoSettings } from "./settings";

const STORAGE_KEY = "clipper.settings.v2";

export function loadSettings(): VideoSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SETTINGS;

    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return DEFAULT_SETTINGS;

    // Campos ausentes (versão anterior do app) caem no default; valores fora
    // da faixa são presos pela normalização.
    return normalizeSettings({ ...DEFAULT_SETTINGS, ...(parsed as Partial<VideoSettings>) });
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function saveSettings(settings: VideoSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // Preferência é conveniência: sem storage o app continua funcionando.
  }
}

export function clearSettings(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Idem.
  }
}

/** Pasta padrão: `Videos\Clipper` do próprio usuário, resolvida pelo sistema. */
export async function defaultOutputDirectory(): Promise<string | null> {
  if (!isTauri()) return null;
  try {
    const { videoDir, join } = await import("@tauri-apps/api/path");
    return await join(await videoDir(), "Clipper");
  } catch {
    return null;
  }
}

/** Abre o seletor nativo. `null` quando o usuário cancela. */
export async function chooseOutputDirectory(current: string | null): Promise<string | null> {
  if (!isTauri()) return null;
  const { open } = await import("@tauri-apps/plugin-dialog");
  const selected = await open({
    directory: true,
    multiple: false,
    title: "Escolher pasta de saída",
    defaultPath: current ?? undefined,
  });
  return typeof selected === "string" ? selected : null;
}

/** Seletor nativo de arquivos de vídeo. Lista vazia quando o usuário cancela. */
export async function chooseVideoFiles(): Promise<string[]> {
  if (!isTauri()) return [];
  const { open } = await import("@tauri-apps/plugin-dialog");
  const selected = await open({
    multiple: true,
    title: "Selecionar vídeos",
    filters: [{ name: "Vídeos", extensions: VIDEO_EXTENSIONS }],
  });

  if (Array.isArray(selected)) return selected;
  return typeof selected === "string" ? [selected] : [];
}

export async function revealFolder(path: string): Promise<void> {
  if (!isTauri()) return;
  const { openPath } = await import("@tauri-apps/plugin-opener");
  await openPath(path);
}

/** Encurta o caminho para caber na interface; o title mostra o completo. */
export function shortenPath(path: string | null, max = 34): string {
  if (!path) return "Não definida";
  if (path.length <= max) return path;
  return `…${path.slice(-(max - 1))}`;
}
