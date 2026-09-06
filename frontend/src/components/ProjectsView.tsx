import { FolderOpen, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ProjectCard } from "./ProjectCard";
import { Segmented } from "./controls";
import { ApiError, api } from "../lib/api";
import { FILTER_OPTIONS, matchesFilter, matchesSearch } from "../lib/format";
import type { ProjectFilter } from "../lib/format";
import { revealFolder } from "../lib/preferences";
import type { VideoSummary } from "../lib/types";

interface Props {
  onOpen: (videoId: string) => void;
  onCreate: () => void;
}

// Projetos em andamento mudam sozinhos; um refresh moderado basta.
const REFRESH_MS = 5000;
const PAGE_SIZE = 30;

export function ProjectsView({ onOpen, onCreate }: Props) {
  const [projects, setProjects] = useState<VideoSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<ProjectFilter>("all");
  const [search, setSearch] = useState("");
  const [pendingDelete, setPendingDelete] = useState<VideoSummary | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const page = await api.listVideos(PAGE_SIZE, 0, signal);
      setProjects(page.items);
      setError(null);
    } catch (caught) {
      if (signal?.aborted) return;
      setError(caught instanceof ApiError ? caught.message : "Não foi possível carregar.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);

    // Só recarrega enquanto houver projeto em andamento.
    const timer = setInterval(() => {
      void load(controller.signal);
    }, REFRESH_MS);

    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [load]);

  const counts = useMemo(() => {
    let processing = 0;
    let done = 0;
    let failed = 0;
    for (const project of projects) {
      if (matchesFilter(project.status, "done")) done += 1;
      else if (matchesFilter(project.status, "failed")) failed += 1;
      else processing += 1;
    }
    return { processing, done, failed };
  }, [projects]);

  const visible = useMemo(
    () =>
      projects.filter(
        (project) =>
          matchesFilter(project.status, filter) &&
          matchesSearch(project.title, project.source_url ?? "", search),
      ),
    [projects, filter, search],
  );

  const retry = async (videoId: string) => {
    try {
      await api.retryVideo(videoId);
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Não foi possível tentar de novo.");
    }
  };

  const remove = async (project: VideoSummary) => {
    setPendingDelete(null);
    try {
      await api.deleteVideo(project.id);
      setProjects((current) => current.filter((item) => item.id !== project.id));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Não foi possível excluir.");
    }
  };

  if (!loading && projects.length === 0) {
    return (
      <section className="projects">
        <header className="projects__header">
          <h1>Projetos</h1>
        </header>
        <div className="empty">
          <FolderOpen size={28} className="empty__icon" aria-hidden="true" />
          <p>Nenhum projeto ainda</p>
          <p className="empty__hint">Cole um link na Home para gerar seus primeiros clips.</p>
          <button type="button" className="button button--primary" onClick={onCreate}>
            Criar projeto
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="projects">
      <header className="projects__header">
        <h1>Projetos</h1>
        <div className="projects__tools">
          <label className="projects__search">
            <Search size={14} aria-hidden="true" />
            <input
              type="search"
              placeholder="Buscar"
              aria-label="Buscar projetos"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          <Segmented
            label="Filtrar projetos"
            value={filter}
            options={FILTER_OPTIONS}
            onChange={setFilter}
          />
        </div>
      </header>

      {projects.length > 1 && (
        <p className="projects__counts">
          {counts.processing} processando · {counts.done} concluídos · {counts.failed} falhou
        </p>
      )}

      {error && <p className="message message--error">{error}</p>}

      {visible.length === 0 ? (
        <p className="message message--warn">Nenhum projeto corresponde ao filtro.</p>
      ) : (
        <div className="projects__list">
          {visible.map((project) => (
            <ProjectCard
              key={project.id}
              project={project}
              onOpen={onOpen}
              onRetry={(id) => void retry(id)}
              onDelete={(id) =>
                setPendingDelete(projects.find((item) => item.id === id) ?? null)
              }
              onRevealFolder={(path) => void revealFolder(path)}
            />
          ))}
        </div>
      )}

      {pendingDelete && (
        <div className="dialog" role="dialog" aria-modal="true" aria-label="Excluir projeto">
          <div className="dialog__box">
            <h2>Excluir projeto?</h2>
            <p>
              Isso remove o projeto e os arquivos temporários internos. Os clips já exportados
              para sua pasta serão mantidos.
            </p>
            <div className="dialog__actions">
              <button
                type="button"
                className="button button--ghost"
                onClick={() => setPendingDelete(null)}
              >
                Cancelar
              </button>
              <button
                type="button"
                className="button button--primary"
                onClick={() => void remove(pendingDelete)}
              >
                Excluir
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
