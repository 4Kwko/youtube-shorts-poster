/** Mapeia o estado real do vídeo para as quatro etapas exibidas. */

import type { Video, VideoStatus } from "./types";

export const STAGES = ["importing", "transcribing", "clipping", "rendering"] as const;

export type StageId = (typeof STAGES)[number];
export type StageState = "done" | "current" | "pending" | "failed";

export const STAGE_LABELS: Record<StageId, string> = {
  importing: "Importando",
  transcribing: "Transcrevendo",
  clipping: "Criando clips",
  rendering: "Renderizando",
};

// Índice da etapa que cada status representa. Status de conclusão apontam para
// a etapa seguinte, que é a que passa a estar em andamento.
const STATUS_STAGE: Record<VideoStatus, number> = {
  pending: 0,
  queued: 0,
  downloading: 0,
  downloaded: 1,
  transcribing: 1,
  transcribed: 2,
  clipped: 3,
  processing: 3,
  rendered: 4,
  // A exportação é a última parte da renderização para quem está olhando.
  exporting: 3,
  exported: 4,
  completed: 4,
  failed: -1,
  cancelled: -1,
};

/**
 * `processing` cobre clipping e renderização; `current_stage` do backend é o
 * que desempata. Nunca inventamos progresso: só traduzimos o que veio.
 */
function activeIndex(video: Video): number {
  if (video.status === "processing" && video.current_stage?.startsWith("clipping")) {
    return 2;
  }
  return STATUS_STAGE[video.status];
}

export function stageStates(video: Video): Record<StageId, StageState> {
  const active = activeIndex(video);
  const failed = video.status === "failed" || video.status === "cancelled";

  const states = {} as Record<StageId, StageState>;
  STAGES.forEach((stage, index) => {
    if (failed) {
      states[stage] = "failed";
    } else if (index < active) {
      states[stage] = "done";
    } else if (index === active) {
      states[stage] = "current";
    } else {
      states[stage] = "pending";
    }
  });
  return states;
}
