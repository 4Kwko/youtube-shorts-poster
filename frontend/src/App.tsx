import { useCallback, useEffect, useRef, useState } from "react";

import { AppShell } from "./components/AppShell";
import { HomeView } from "./components/HomeView";
import { ProcessingView } from "./components/ProcessingView";
import { ProjectsView } from "./components/ProjectsView";
import { ResultsView } from "./components/ResultsView";
import { SettingsView } from "./components/SettingsView";
import { useAppSettings } from "./hooks/useAppSettings";
import { useBackendHealth } from "./hooks/useBackendHealth";
import { useVideoProgress } from "./hooks/useVideoProgress";
import { ApiError, api } from "./lib/api";
import type { NavKey } from "./lib/navigation";
import { resolveView } from "./lib/navigation";
import { revealFolder } from "./lib/preferences";
import { partition } from "./lib/queue";
import type { QueueItem } from "./lib/queue";
import { buildBatchPayload, normalizeSettings } from "./lib/settings";
import type { Video } from "./lib/types";

export default function App() {
  const engine = useBackendHealth();
  const appSettings = useAppSettings();
  const [nav, setNav] = useState<NavKey>("home");
  const [videoId, setVideoId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const { video, clips, error: pollError } = useVideoProgress(videoId);
  const view = resolveView({ nav, videoId, status: video?.status ?? null });

  // Abre a pasta uma vez, e só quando a exportação terminou de verdade.
  const openedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!video || video.status !== "exported") return;
    if (!video.settings.open_output_folder || !video.settings.output_directory) return;
    if (openedFor.current === video.id) return;

    openedFor.current = video.id;
    void revealFolder(video.settings.output_directory);
  }, [video]);

  const start = useCallback(
    async (items: QueueItem[]) => {
      setSubmitting(true);
      setSubmitError(null);
      try {
        // Um snapshot por envio: alterar Configurações depois não muda estes
        // vídeos. URLs e arquivos usam endpoints próprios — um payload misto
        // esconderia validações bem diferentes.
        const { urls, paths } = partition(items);
        const settings = normalizeSettings(appSettings.settings);
        const videos: Video[] = [];

        if (urls.length > 0) {
          const remote = await api.createVideos(buildBatchPayload(urls, settings));
          videos.push(...remote.videos);
        }
        if (paths.length > 0) {
          const local = await api.createLocalVideos({ paths, settings });
          videos.push(...local.videos);
        }

        if (videos.length === 1 && videos[0]) {
          // Envio único: acompanha o processamento direto.
          setVideoId(videos[0].id);
          setNav("home");
          return;
        }

        // Vários: Projetos é a tela de acompanhamento.
        setVideoId(null);
        setNav("projects");
      } catch (caught) {
        setSubmitError(
          caught instanceof ApiError
            ? caught.message
            : "Não foi possível iniciar o processamento.",
        );
      } finally {
        setSubmitting(false);
      }
    },
    [appSettings.settings],
  );

  // Fecha o vídeo aberto sem sair da aba: voltar de um projeto retorna para
  // Projetos, e voltar de uma criação retorna para a Home.
  const closeVideo = useCallback(() => {
    setVideoId(null);
    setSubmitError(null);
  }, []);

  return (
    <AppShell
      nav={nav}
      view={view}
      engine={engine.state}
      engineMessage={engine.message}
      onNavigate={setNav}
      onRetryEngine={engine.retry}
    >
      {view === "home" && (
        <HomeView
          settings={appSettings.settings}
          disabled={engine.state !== "ready"}
          submitting={submitting}
          error={submitError}
          onSubmit={(items) => void start(items)}
          onEditSettings={() => setNav("settings")}
        />
      )}

      {view === "processing" && (
        <ProcessingView video={video} error={pollError} onRestart={closeVideo} />
      )}

      {view === "results" && video && (
        <ResultsView video={video} clips={clips} onRestart={closeVideo} />
      )}

      {view === "projects" && (
        <ProjectsView
          onOpen={(id) => setVideoId(id)}
          onCreate={() => setNav("home")}
        />
      )}

      {view === "settings" && (
        <SettingsView
          settings={appSettings.settings}
          engine={engine.state}
          health={engine.health}
          message={engine.message}
          onChange={appSettings.update}
          onReset={appSettings.reset}
        />
      )}
    </AppShell>
  );
}
