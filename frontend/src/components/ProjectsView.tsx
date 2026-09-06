import {
  CheckCircle2,
  Clock3,
  FolderOpen,
  Layers,
  Plus,
  Search,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ConfirmDialog } from "./ConfirmDialog";
import { ProjectCard } from "./ProjectCard";
import { Segmented } from "./controls";
import { Button, EmptyState } from "./ui";
import { ApiError, api } from "../lib/api";
import { FILTER_OPTIONS, matchesFilter, matchesSearch } from "../lib/format";
import type { ProjectFilter } from "../lib/format";
import { revealFolder } from "../lib/preferences";
import type { VideoSummary } from "../lib/types";

interface Props {
  onOpen: (videoId: string) => void;
  onCreate: () => void;
}
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
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Não foi possível carregar.",
      );
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    const timer = setInterval(() => void load(controller.signal), REFRESH_MS);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [load]);
  const counts = useMemo(() => {
    let processing = 0;
    let done = 0;
    let clips = 0;
    for (const project of projects) {
      if (matchesFilter(project.status, "done")) done += 1;
      else if (!matchesFilter(project.status, "failed")) processing += 1;
      clips += project.clip_count;
    }
    return { processing, done, clips };
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
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Não foi possível tentar de novo.",
      );
    }
  };
  const remove = async (project: VideoSummary) => {
    setPendingDelete(null);
    try {
      await api.deleteVideo(project.id);
      setProjects((current) =>
        current.filter((item) => item.id !== project.id),
      );
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Não foi possível excluir.",
      );
    }
  };
  return (
    <section className="projects">
      <header className="page-heading">
        <div>
          <span className="eyebrow">BIBLIOTECA</span>
          <h1>Seus projetos</h1>
          <p>Da fila ao último corte, acompanhe cada vídeo por aqui.</p>
        </div>
        <Button variant="primary" onClick={onCreate}>
          <Plus size={15} aria-hidden="true" />
          Novo projeto
        </Button>
      </header>
      {error && (
        <p role="alert" className="message message--error">
          {error}{" "}
          <Button variant="ghost" onClick={() => void load()}>
            Tentar novamente
          </Button>
        </p>
      )}
      {loading ? (
        <div
          className="projects__list"
          role="status"
          aria-label="Carregando projetos"
        >
          <div className="skeleton" />
          <div className="skeleton" />
          <div className="skeleton" />
        </div>
      ) : projects.length === 0 && !error ? (
        <EmptyState
          title="Nenhum projeto ainda."
          action={
            <Button variant="primary" onClick={onCreate}>
              <Plus size={15} aria-hidden="true" />
              Criar primeiro projeto
            </Button>
          }
        >
          Cole um vídeo na Home e prepare seus primeiros cortes com o SignalCut.
        </EmptyState>
      ) : (
        projects.length > 0 && (
          <>
            <div
              className="projects__stats"
              aria-label="Resumo dos projetos carregados"
            >
              <div className="project-stat">
                <FolderOpen size={20} aria-hidden="true" />
                <div>
                  <strong className="mono">{projects.length}</strong>
                  <span>Projetos</span>
                </div>
              </div>
              <div className="project-stat">
                <Clock3 size={20} aria-hidden="true" />
                <div>
                  <strong className="mono">{counts.processing}</strong>
                  <span>Em andamento</span>
                </div>
              </div>
              <div className="project-stat">
                <Layers size={20} aria-hidden="true" />
                <div>
                  <strong className="mono">{counts.clips}</strong>
                  <span>Clipes criados</span>
                </div>
              </div>
              <div className="project-stat">
                <CheckCircle2 size={20} aria-hidden="true" />
                <div>
                  <strong className="mono">{counts.done}</strong>
                  <span>Concluídos</span>
                </div>
              </div>
            </div>
            <p className="projects__scope">
              Resumo dos últimos {PAGE_SIZE} projetos, quando disponíveis.
            </p>
            <div className="projects__tools">
              <Segmented
                label="Filtrar projetos"
                value={filter}
                options={FILTER_OPTIONS}
                onChange={setFilter}
              />
              <label className="projects__search">
                <Search size={15} aria-hidden="true" />
                <input
                  type="search"
                  placeholder="Buscar por título ou link"
                  aria-label="Buscar projetos"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              </label>
            </div>
            {visible.length === 0 ? (
              <EmptyState title="Nenhum resultado para este filtro.">
                Experimente outro título, link ou estado de processamento.
              </EmptyState>
            ) : (
              <div className="projects__list">
                {visible.map((project) => (
                  <ProjectCard
                    key={project.id}
                    project={project}
                    onOpen={onOpen}
                    onRetry={(id) => void retry(id)}
                    onDelete={(id) =>
                      setPendingDelete(
                        projects.find((item) => item.id === id) ?? null,
                      )
                    }
                    onRevealFolder={(path) => void revealFolder(path)}
                  />
                ))}
              </div>
            )}
          </>
        )
      )}
      {pendingDelete && (
        <ConfirmDialog
          onCancel={() => setPendingDelete(null)}
          onConfirm={() => void remove(pendingDelete)}
        />
      )}
    </section>
  );
}
