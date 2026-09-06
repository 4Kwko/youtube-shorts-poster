import { ClipCard } from "./ClipCard";
import { SettingsSummary } from "./SettingsSummary";
import type { Clip, Video } from "../lib/types";

interface Props {
  video: Video;
  clips: Clip[];
  onRestart: () => void;
}

export function ResultsView({ video, clips, onRestart }: Props) {
  return (
    <section className="results">
      <header className="results__header">
        <div>
          <h1>{clips.length} clips prontos</h1>
          {video.title && <p className="results__subject">{video.title}</p>}
          <SettingsSummary settings={video.settings} />
        </div>
        <button type="button" className="button button--ghost" onClick={onRestart}>
          Novo vídeo
        </button>
      </header>

      {clips.length === 0 ? (
        <p className="message message--warn">Nenhum clip foi gerado para este vídeo.</p>
      ) : (
        <div className="clips">
          {clips.map((clip) => (
            <ClipCard key={clip.id} clip={clip} />
          ))}
        </div>
      )}
    </section>
  );
}
