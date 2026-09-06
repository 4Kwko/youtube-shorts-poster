import {
  Check,
  Clock3,
  Film,
  FolderOpen,
  MoreHorizontal,
  Play,
  RotateCcw,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { useRef } from "react";
import { Badge, Button, Progress } from "./ui";
import { thumbnailUrl } from "../lib/api";
import { formatVideoDuration, humanDate, statusLabel } from "../lib/format";
import { layoutName, summaryItems } from "../lib/settings";
import type { VideoSummary } from "../lib/types";
interface Props {
  project: VideoSummary;
  onOpen: (videoId: string) => void;
  onRetry: (videoId: string) => void;
  onDelete: (videoId: string) => void;
  onRevealFolder: (path: string) => void;
}
const OPENABLE = ["rendered", "exported", "completed"];
const BROKEN = ["failed", "cancelled"];
export function ProjectCard({
  project,
  onOpen,
  onRetry,
  onDelete,
  onRevealFolder,
}: Props) {
  const menu = useRef<HTMLDetailsElement>(null);
  const done = OPENABLE.includes(project.status);
  const failed = BROKEN.includes(project.status);
  const queued = ["pending", "queued"].includes(project.status);
  const processing = !done && !failed;
  const folder =
    project.status === "exported" ? project.settings.output_directory : null;
  const closeMenu = () => {
    if (menu.current) menu.current.open = false;
  };
  return (
    <article className={`project ${failed ? "project--failed" : ""}`}>
      <button
        type="button"
        className="project__thumb"
        onClick={() => onOpen(project.id)}
        aria-label={`Abrir ${project.title ?? "projeto"}`}
      >
        {project.has_thumbnail ? (
          <img src={thumbnailUrl(project.id)} alt="" loading="lazy" />
        ) : (
          <Film size={24} aria-hidden="true" />
        )}
        <span className="project__thumb-play">
          <Play size={16} aria-hidden="true" />
        </span>
      </button>
      <div className="project__body">
        <div className="project__topline">
          <Badge
            tone={
              failed ? "danger" : done ? "success" : queued ? "neutral" : "info"
            }
          >
            {failed ? (
              <TriangleAlert size={11} aria-hidden="true" />
            ) : done ? (
              <Check size={11} aria-hidden="true" />
            ) : (
              <Clock3 size={11} aria-hidden="true" />
            )}
            {statusLabel(project.status)}
          </Badge>
          <span className="project__date">{humanDate(project.created_at)}</span>
        </div>
        <h3 className="project__title">
          <button type="button" onClick={() => onOpen(project.id)}>
            {project.title ?? project.source_url ?? "Arquivo local"}
          </button>
        </h3>
        <p className="project__facts">
          {project.source_type === "local" ? "Arquivo local" : project.provider}{" "}
          · {formatVideoDuration(project.duration)} · {project.clip_count}{" "}
          clipes · {layoutName(project.settings.layout)}
        </p>
        {processing ? (
          <div className="project__progress">
            <Progress
              value={project.progress}
              label={`Progresso de ${project.title ?? "projeto"}`}
            />
            <span className="mono">{project.progress}%</span>
          </div>
        ) : (
          <ul className="summary-tags summary-tags--muted">
            {summaryItems(project.settings)
              .slice(2)
              .map((item) => (
                <li key={item.label}>{item.label}</li>
              ))}
          </ul>
        )}
      </div>
      <div className="project__actions">
        <Button variant="secondary" onClick={() => onOpen(project.id)}>
          <Play size={13} aria-hidden="true" />
          {done ? "Ver clipes" : "Acompanhar"}
        </Button>
        <details
          className="menu"
          ref={menu}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              closeMenu();
              menu.current?.querySelector("summary")?.focus();
            }
          }}
        >
          <summary
            className="button button--icon"
            aria-label="Mais ações"
            title="Mais ações"
          >
            <MoreHorizontal size={17} aria-hidden="true" />
          </summary>
          <div className="menu__items">
            {failed && (
              <button
                type="button"
                onClick={() => {
                  closeMenu();
                  onRetry(project.id);
                }}
              >
                <RotateCcw size={14} aria-hidden="true" />
                Tentar novamente
              </button>
            )}
            {folder && (
              <button
                type="button"
                onClick={() => {
                  closeMenu();
                  onRevealFolder(folder);
                }}
              >
                <FolderOpen size={14} aria-hidden="true" />
                Abrir pasta
              </button>
            )}
            <button
              type="button"
              className="menu__danger"
              onClick={() => {
                closeMenu();
                onDelete(project.id);
              }}
            >
              <Trash2 size={14} aria-hidden="true" />
              Excluir projeto
            </button>
          </div>
        </details>
      </div>
    </article>
  );
}
