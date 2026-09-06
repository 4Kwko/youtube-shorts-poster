import { useState } from "react";

import { ColorChoice, Field, Segmented, Slider, Toggle } from "./controls";
import { ExportSettings } from "./ExportSettings";
import { LayoutPreview } from "./LayoutPreview";
import { apiBaseUrl } from "../lib/api";
import type { EngineState } from "../lib/engine";
import { ENGINE_LABELS } from "../lib/engine";
import {
  CLIP_DURATION_OPTIONS,
  FOREGROUND_SCALE_MAX,
  FOREGROUND_SCALE_MIN,
  FPS_OPTIONS,
  LAYOUT_OPTIONS,
  OUTLINE_COLOR_PRESETS,
  QUALITY_OPTIONS,
  SUBTITLE_FONT_SIZE_MAX,
  SUBTITLE_FONT_SIZE_MIN,
  SUBTITLE_OFFSET_LIMIT,
  SUBTITLE_POSITION_OPTIONS,
  SUBTITLE_STYLE_OPTIONS,
  TEXT_COLOR_PRESETS,
  durationAtIndex,
  durationIndex,
  usesBackground,
} from "../lib/settings";
import type { VideoSettings } from "../lib/settings";
import type { Health } from "../lib/types";

interface Props {
  settings: VideoSettings;
  engine: EngineState;
  health: Health | null;
  message: string | null;
  onChange: (next: VideoSettings) => void;
  onReset: () => void;
}

interface SectionProps {
  title: string;
  children: React.ReactNode;
}

function Section({ title, children }: SectionProps) {
  return (
    <section className="settings-section">
      <h2 className="settings-section__title">{title}</h2>
      <div className="settings-section__body">{children}</div>
    </section>
  );
}

/**
 * Defaults do app. O que estiver aqui vale para o próximo vídeo gerado; um
 * vídeo já em processamento mantém o snapshot que levou.
 */
export function SettingsView({
  settings,
  engine,
  health,
  message,
  onChange,
  onReset,
}: Props) {
  const [confirmingReset, setConfirmingReset] = useState(false);
  const set = (patch: Partial<VideoSettings>) =>
    onChange({ ...settings, ...patch });

  const subtitles = settings.subtitles_enabled;
  const composed = usesBackground(settings.layout);

  return (
    <div className="settings-page">
      <header className="page-heading">
        <div>
          <span className="eyebrow">PREFERÊNCIAS DO STUDIO</span>
          <h1>Seu jeito de criar.</h1>
          <p>
            Os ajustes são salvos automaticamente para os próximos projetos.
          </p>
        </div>
      </header>
      <div className="settings-page__columns">
        <div className="settings-page__column">
          <Section title="Duração dos clipes">
            <Slider
              label="Duração"
              value={durationIndex(settings.clip_duration_seconds)}
              min={0}
              max={CLIP_DURATION_OPTIONS.length - 1}
              minLabel={`${CLIP_DURATION_OPTIONS[0]}s`}
              maxLabel={`${CLIP_DURATION_OPTIONS[CLIP_DURATION_OPTIONS.length - 1]}s`}
              display={`${settings.clip_duration_seconds}s`}
              // O slider anda por índice: a lista não é progressão regular.
              onChange={(index) =>
                set({ clip_duration_seconds: durationAtIndex(index) })
              }
            />
          </Section>

          <Section title="Vídeo">
            <Field label="Layout">
              <div
                className="layouts"
                role="radiogroup"
                aria-label="Layout do vídeo"
              >
                {LAYOUT_OPTIONS.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    role="radio"
                    aria-checked={settings.layout === option.id}
                    className="layout-card"
                    onClick={() => set({ layout: option.id })}
                  >
                    <span className="layout-card__head">
                      <span className="layout-card__name">{option.name}</span>
                    </span>
                    <LayoutPreview
                      settings={{ ...settings, layout: option.id }}
                      compact
                    />
                  </button>
                ))}
              </div>
            </Field>

            {composed && (
              <>
                <Slider
                  label="Intensidade do blur"
                  value={settings.blur_strength}
                  min={0}
                  max={100}
                  step={5}
                  minLabel="Suave"
                  maxLabel="Forte"
                  display={`${settings.blur_strength}%`}
                  onChange={(blur_strength) => set({ blur_strength })}
                />
                <Slider
                  label="Escurecer fundo"
                  value={settings.background_darkness}
                  min={0}
                  max={100}
                  step={5}
                  minLabel="Claro"
                  maxLabel="Escuro"
                  display={`${settings.background_darkness}%`}
                  onChange={(background_darkness) =>
                    set({ background_darkness })
                  }
                />
                <Slider
                  label="Tamanho do vídeo"
                  value={settings.foreground_scale}
                  min={FOREGROUND_SCALE_MIN}
                  max={FOREGROUND_SCALE_MAX}
                  step={5}
                  minLabel="Menor"
                  maxLabel="Maior"
                  display={`${settings.foreground_scale}%`}
                  onChange={(foreground_scale) => set({ foreground_scale })}
                />
              </>
            )}

            <Field label="Qualidade">
              <Segmented
                label="Qualidade"
                value={settings.render_quality}
                options={QUALITY_OPTIONS}
                onChange={(render_quality) => set({ render_quality })}
              />
            </Field>

            <Field label="FPS">
              <Segmented
                label="FPS"
                value={settings.output_fps}
                options={FPS_OPTIONS}
                onChange={(output_fps) => set({ output_fps })}
              />
            </Field>
          </Section>
        </div>

        <div className="settings-page__column">
          <Section title="Legendas">
            <Toggle
              label="Legendas"
              checked={subtitles}
              onChange={(subtitles_enabled) => set({ subtitles_enabled })}
            />

            {subtitles && (
              <>
                <Slider
                  label="Tamanho"
                  value={settings.subtitle_font_size}
                  min={SUBTITLE_FONT_SIZE_MIN}
                  max={SUBTITLE_FONT_SIZE_MAX}
                  display={`${settings.subtitle_font_size}px`}
                  onChange={(subtitle_font_size) => set({ subtitle_font_size })}
                />
                <Field label="Posição">
                  <Segmented
                    label="Posição da legenda"
                    value={settings.subtitle_position}
                    options={SUBTITLE_POSITION_OPTIONS}
                    onChange={(subtitle_position) => set({ subtitle_position })}
                  />
                </Field>
                <Slider
                  label="Altura"
                  value={settings.subtitle_vertical_offset}
                  min={-SUBTITLE_OFFSET_LIMIT}
                  max={SUBTITLE_OFFSET_LIMIT}
                  step={20}
                  minLabel="Mais baixo"
                  maxLabel="Mais alto"
                  display={
                    settings.subtitle_vertical_offset === 0
                      ? "Sem ajuste"
                      : `${settings.subtitle_vertical_offset > 0 ? "+" : ""}${settings.subtitle_vertical_offset}px`
                  }
                  onChange={(subtitle_vertical_offset) =>
                    set({ subtitle_vertical_offset })
                  }
                />
                <Field label="Estilo">
                  <Segmented
                    label="Estilo da legenda"
                    value={settings.subtitle_style}
                    options={SUBTITLE_STYLE_OPTIONS}
                    onChange={(subtitle_style) => set({ subtitle_style })}
                  />
                </Field>
                <ColorChoice
                  label="Texto"
                  value={settings.subtitle_text_color}
                  presets={TEXT_COLOR_PRESETS}
                  onChange={(subtitle_text_color) =>
                    set({ subtitle_text_color })
                  }
                />
                <ColorChoice
                  label="Contorno"
                  value={settings.subtitle_outline_color}
                  presets={OUTLINE_COLOR_PRESETS}
                  onChange={(subtitle_outline_color) =>
                    set({ subtitle_outline_color })
                  }
                />
              </>
            )}
          </Section>

          <Section title="Áudio">
            <Slider
              label="Volume"
              value={settings.volume}
              min={0}
              max={100}
              step={5}
              minLabel="0%"
              maxLabel="100%"
              display={`${settings.volume}%`}
              onChange={(volume) => set({ volume })}
            />
            <Toggle
              label="Normalizar volume"
              checked={settings.normalize_audio}
              onChange={(normalize_audio) => set({ normalize_audio })}
            />
          </Section>

          <Section title="Exportação">
            <ExportSettings value={settings} disabled={false} onChange={set} />
          </Section>

          <Section title="Motor">
            <dl className="engine-info">
              <div>
                <dt>Estado</dt>
                <dd>{ENGINE_LABELS[engine]}</dd>
              </div>
              <div>
                <dt>API local</dt>
                <dd>{apiBaseUrl()}</dd>
              </div>
              <div>
                <dt>Backend</dt>
                <dd>{health?.version ?? "—"}</dd>
              </div>
              <div>
                <dt>FFmpeg</dt>
                <dd>
                  {health
                    ? health.dependencies.ffmpeg
                      ? "Disponível"
                      : "Ausente"
                    : "—"}
                </dd>
              </div>
            </dl>
            {message && <p className="message message--error">{message}</p>}
          </Section>
        </div>
      </div>

      <footer className="settings-page__footer">
        {confirmingReset ? (
          <div className="settings-page__confirm">
            <span>Restaurar todos os padrões?</span>
            <button
              type="button"
              className="button button--primary"
              onClick={() => {
                onReset();
                setConfirmingReset(false);
              }}
            >
              Restaurar
            </button>
            <button
              type="button"
              className="button button--ghost"
              onClick={() => setConfirmingReset(false)}
            >
              Cancelar
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="button button--ghost"
            onClick={() => setConfirmingReset(true)}
          >
            Restaurar padrões
          </button>
        )}
      </footer>
    </div>
  );
}
