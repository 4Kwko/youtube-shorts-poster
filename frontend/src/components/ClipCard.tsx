import { Download } from "lucide-react";

import { mediaUrl } from "../lib/api";
import { downloadFile } from "../lib/download";
import { formatDuration, formatTimecode } from "../lib/time";
import type { Clip } from "../lib/types";

interface Props {
  clip: Clip;
}

export function ClipCard({ clip }: Props) {
  const source = clip.media_url ? mediaUrl(clip.media_url) : null;
  const download = clip.download_url ? mediaUrl(clip.download_url) : null;
  const label = `Clip ${String(clip.sequence + 1).padStart(2, "0")}`;

  return (
    <article className="clip">
      <div className="clip__frame">
        {source ? (
          // `preload="metadata"` evita baixar todos os clips ao abrir a lista.
          <video className="clip__video" src={source} controls preload="metadata" />
        ) : (
          <p className="clip__unavailable">Render indisponível</p>
        )}
      </div>

      <div className="clip__meta">
        <div className="clip__labels">
          <p className="clip__title">{label}</p>
          <p className="clip__range">
            {formatTimecode(clip.start_time)} → {formatTimecode(clip.end_time)}
          </p>
        </div>

        <span className="clip__duration">{formatDuration(clip.duration)}</span>

        {download && (
          <div className="clip__actions">
            <button
              type="button"
              className="button button--icon"
              title={`Baixar ${label}`}
              aria-label={`Baixar ${label}`}
              onClick={() => void downloadFile(download)}
            >
              <Download size={16} />
            </button>
          </div>
        )}
      </div>
    </article>
  );
}
