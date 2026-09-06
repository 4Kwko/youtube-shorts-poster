import { Film, FolderOpen, MoreHorizontal, Play, RotateCcw, Trash2 } from "lucide-react";
import { useState } from "react";

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

export function ProjectCard({ project, onOpen, onRetry, onDelete, onRevealFolder }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);

  const done = OPENABLE.includes(project.status);
  const failed = BROKEN.includes(project.status);
  const processing = !done && !failed;
  const folder = project.status === "exported" ? project.settings.output_directory : null;

  return (
    <article className="project">
      <div className="project__thumb">
        {project.has_thumbnail ? (
          <img src={thumbnailUrl(project.id)} alt="" loading="lazy" />
        ) : (
          <Film size={20} aria-hidden="true" />
        )}
      </div>

      <div className="project__body">
        <h3 className="project__title">
          {project.title ?? project.source_url ?? "Arquivo local"}
        </h3>

        <p className="project__facts">
          {project.source_type === "local" ? "Local" : project.provider} ·{" "}
          {formatVideoDuration(project.duration)} · {project.clip_count} clips ·{" "}
          {layoutName(project.settings.layout)}
        </p>

        <p className={`project__status project__status--${failed ? "failed" : "ok"}`}>
          {statusLabel(project.status)}
          {processing && ` · ${project.progress}%`}
          {" · "}
          {humanDate(project.created_at)}
        </p>

        <ul className="summary-tags summary-tags--muted">
          {summaryItems(project.settings)
            .slice(2)
            .map((item) => (
              <li key={item.label}>{item.label}</li>
            ))}
        </ul>
      </div>

      <div className="project__actions">
        <button
          type="button"
          className="button button--ghost"
          onClick={() => onOpen(project.id)}
        >
          <Play size={13} aria-hidden="true" />
          Abrir
        </button>

        <div className="menu">
          <button
            type="button"
            className="button button--icon"
            aria-label="Mais ações"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
          >
            <MoreHorizontal size={16} />
          </button>

          {menuOpen && (
            <div className="menu__items" role="menu">
              {failed && (
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setMenuOpen(false);
                    onRetry(project.id);
                  }}
                >
                  <RotateCcw size={13} aria-hidden="true" />
                  Tentar novamente
                </button>
              )}
              {folder && (
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setMenuOpen(false);
                    onRevealFolder(folder);
                  }}
                >
                  <FolderOpen size={13} aria-hidden="true" />
                  Abrir pasta
                </button>
              )}
              <button
                type="button"
                role="menuitem"
                className="menu__danger"
                onClick={() => {
                  setMenuOpen(false);
                  onDelete(project.id);
                }}
              >
                <Trash2 size={13} aria-hidden="true" />
                Excluir projeto
              </button>
            </div>
          )}
        </div>
      </div>
    </article>
  );
}
