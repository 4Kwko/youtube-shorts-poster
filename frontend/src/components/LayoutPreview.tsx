import type { CSSProperties } from "react";

import { usesBackground } from "../lib/settings";
import type { VideoSettings } from "../lib/settings";

interface Props {
  settings: VideoSettings;
  compact?: boolean;
}

/** Fração da altura do canvas ocupada pelo vídeo central, por layout. */
function foregroundHeightRatio(settings: VideoSettings): number {
  const width = settings.foreground_scale / 100;
  if (settings.layout === "blurred_16_9")
    return (width * 1080 * (9 / 16)) / 1920;
  return (width * 1080 * (3 / 4)) / 1920;
}

/** Posição vertical aproximada da legenda, do topo do quadro. */
function subtitleTop(settings: VideoSettings): number {
  const margins = { top: 1360, center: 860, bottom: 420 };
  const margin =
    margins[settings.subtitle_position] + settings.subtitle_vertical_offset;
  const bounded = Math.min(Math.max(margin, 120), 1520);
  return (1920 - bounded) / 1920;
}

/**
 * Mock 9:16 em CSS. Aproxima layout, blur, escurecimento, escala do vídeo e
 * legenda — não tenta ser fiel ao pixel.
 */
export function LayoutPreview({ settings, compact = false }: Props) {
  const withBackground = usesBackground(settings.layout);
  const height = withBackground ? foregroundHeightRatio(settings) : 1;
  const width = withBackground ? settings.foreground_scale / 100 : 1;

  const backgroundStyle: CSSProperties = {
    filter: `blur(${1 + (settings.blur_strength / 100) * 4}px)`,
    opacity: 1 - (settings.background_darkness / 100) * 0.6,
  };

  const foregroundStyle: CSSProperties = {
    height: `${height * 100}%`,
    width: `${width * 100}%`,
  };

  const subtitleStyle: CSSProperties = {
    top: `${subtitleTop(settings) * 100}%`,
    color: settings.subtitle_text_color,
    fontSize: `${(settings.subtitle_font_size / 1920) * 100 * (compact ? 2.4 : 3.4)}px`,
    WebkitTextStroke: `0.5px ${settings.subtitle_outline_color}`,
    fontWeight: settings.subtitle_style === "minimal" ? 500 : 800,
  };

  return (
    <div className={`preview ${compact ? "preview--compact" : ""}`}>
      {withBackground && (
        <span
          className="preview__background"
          style={backgroundStyle}
          aria-hidden="true"
        />
      )}
      <span
        className="preview__foreground"
        style={foregroundStyle}
        aria-hidden="true"
      />
      {settings.subtitles_enabled && (
        <span
          className="preview__subtitle"
          style={subtitleStyle}
          aria-hidden="true"
        >
          legenda
        </span>
      )}
    </div>
  );
}
