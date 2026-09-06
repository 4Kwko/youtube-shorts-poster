import { ArrowLeft, CheckCircle2, Layers } from "lucide-react";
import { ClipCard } from "./ClipCard";
import { SettingsSummary } from "./SettingsSummary";
import { Badge, Button, EmptyState } from "./ui";
import type { Clip, Video } from "../lib/types";
interface Props {
  video: Video;
  clips: Clip[];
  onRestart: () => void;
}
export function ResultsView({ video, clips, onRestart }: Props) {
  return (
    <section className="results">
      <header className="page-heading results__header">
        <div>
          <span className="eyebrow">RESULTADOS / PROJETO</span>
          <h1>
            {clips.length}{" "}
            {clips.length === 1 ? "clipe pronto" : "clipes prontos"}
          </h1>
          {video.title && <p className="results__subject">{video.title}</p>}
        </div>
        <Button variant="ghost" onClick={onRestart}>
          <ArrowLeft size={15} aria-hidden="true" />
          Voltar
        </Button>
      </header>
      <div className="results__toolbar">
        <SettingsSummary settings={video.settings} />
        <Badge tone="success">
          <CheckCircle2 size={12} aria-hidden="true" />
          Renderização concluída
        </Badge>
      </div>
      {clips.length === 0 ? (
        <EmptyState title="Nenhum clipe disponível.">
          Nenhum clipe foi gerado para este vídeo.
        </EmptyState>
      ) : (
        <>
          <div className="results__label">
            <Layers size={15} aria-hidden="true" />
            <span>Revise e baixe seus cortes</span>
            <span className="mono">
              {String(clips.length).padStart(2, "0")} CLIPES
            </span>
          </div>
          <div className="clips">
            {clips.map((clip) => (
              <ClipCard key={clip.id} clip={clip} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}
