/**
 * Estado do motor local visto pela interface.
 *
 * Fora do Tauri (navegador puro), não há motor gerenciado: o backend é
 * responsabilidade de quem rodou o `uvicorn` à mão, então só existe pronto ou
 * indisponível.
 */

import { isTauri } from "./download";

export type EnginePhase = "idle" | "migrating" | "starting" | "ready" | "failed";

export interface EngineStatusPayload {
  phase: EnginePhase;
  message: string | null;
  port: number;
  reused: boolean;
}

export type EngineState = "checking" | "starting" | "ready" | "offline";

export const ENGINE_LABELS: Record<EngineState, string> = {
  checking: "Verificando…",
  starting: "Iniciando motor…",
  ready: "Motor pronto",
  offline: "Falha ao iniciar motor",
};

/** Consulta o processo Tauri. `null` quando não estamos dentro do app. */
export async function getEngineStatus(): Promise<EngineStatusPayload | null> {
  if (!isTauri()) return null;
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<EngineStatusPayload>("engine_status");
}

/**
 * Traduz "health respondeu?" + fase do processo em um estado de tela.
 *
 * O `/health` é a fonte de verdade para `ready`: o motor só está pronto quando
 * a API de fato responde, não quando o Rust acha que subiu.
 */
export function resolveEngineState(
  healthy: boolean,
  status: EngineStatusPayload | null,
): EngineState {
  if (healthy) return "ready";
  if (status === null) return "offline";
  if (status.phase === "failed") return "offline";
  // idle/migrating/starting: ainda em curso, e `ready` sem health é transitório.
  return "starting";
}
