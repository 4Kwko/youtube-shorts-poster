import { useEffect, useState } from "react";

import { ApiError, api } from "../lib/api";
import type { Clip, Video } from "../lib/types";
import { hasClips, isFinished } from "../lib/types";

const POLL_INTERVAL_MS = 1800;

interface ProgressState {
  video: Video | null;
  clips: Clip[];
  error: string | null;
}

/**
 * Acompanha um vídeo até um estado terminal.
 *
 * Usa `setTimeout` encadeado, não `setInterval`: o próximo request só é
 * agendado quando o anterior termina, então uma resposta lenta nunca acumula
 * chamadas concorrentes. O `AbortController` corta tudo na desmontagem.
 */
export function useVideoProgress(videoId: string | null): ProgressState {
  const [video, setVideo] = useState<Video | null>(null);
  const [clips, setClips] = useState<Clip[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!videoId) return;

    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;

    const poll = async () => {
      try {
        const current = await api.getVideo(videoId, controller.signal);
        if (stopped) return;

        setVideo(current);
        setError(null);

        if (hasClips(current.status)) {
          const result = await api.listClips(videoId, controller.signal);
          if (!stopped) setClips(result);
        }

        if (!isFinished(current)) {
          timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
        }
      } catch (caught) {
        if (stopped || controller.signal.aborted) return;
        setError(
          caught instanceof ApiError
            ? caught.message
            : "Perdemos contato com o motor local.",
        );
        // Falha de rede não encerra o acompanhamento: tenta de novo.
        timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
      }
    };

    void poll();

    return () => {
      stopped = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [videoId]);

  return { video, clips, error };
}
