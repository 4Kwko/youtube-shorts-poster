/**
 * Configuração de processamento por vídeo.
 *
 * Espelha `backend/app/schemas/settings.py`. Uma definição só, importada por
 * quem precisar — nada de duração, layout ou faixa escrita à mão em componente.
 */

export type VideoLayout = "center_crop" | "blurred_4_3" | "blurred_16_9";
export type SubtitlePosition = "top" | "center" | "bottom";
export type SubtitleStyleName = "bold" | "minimal" | "outline";
export type RenderQuality = "fast" | "balanced" | "high";
export type OutputFps = "original" | "30" | "60";
export type FilenamePattern = "clip" | "title";

export const CLIP_DURATION_OPTIONS = [
  30, 60, 90, 120, 150, 180,
] as const;

export type ClipDuration = (typeof CLIP_DURATION_OPTIONS)[number];

export const SUBTITLE_FONT_SIZE_MIN = 48;
export const SUBTITLE_FONT_SIZE_MAX = 110;
export const SUBTITLE_OFFSET_LIMIT = 400;
export const FOREGROUND_SCALE_MIN = 60;
export const FOREGROUND_SCALE_MAX = 100;

export interface VideoSettings {
  version: number;
  clip_duration_seconds: number;
  layout: VideoLayout;
  blur_strength: number;
  background_darkness: number;
  foreground_scale: number;
  subtitles_enabled: boolean;
  subtitle_font_size: number;
  subtitle_position: SubtitlePosition;
  subtitle_vertical_offset: number;
  subtitle_style: SubtitleStyleName;
  subtitle_text_color: string;
  subtitle_outline_color: string;
  render_quality: RenderQuality;
  output_fps: OutputFps;
  volume: number;
  normalize_audio: boolean;
  output_directory: string | null;
  filename_pattern: FilenamePattern;
  open_output_folder: boolean;
  keep_original: boolean;
}

export const DEFAULT_SETTINGS: VideoSettings = {
  version: 1,
  clip_duration_seconds: 90,
  layout: "blurred_4_3",
  blur_strength: 40,
  background_darkness: 34,
  foreground_scale: 100,
  subtitles_enabled: true,
  subtitle_font_size: 72,
  subtitle_position: "bottom",
  subtitle_vertical_offset: 0,
  subtitle_style: "bold",
  subtitle_text_color: "#FFFFFF",
  subtitle_outline_color: "#000000",
  render_quality: "balanced",
  output_fps: "original",
  volume: 100,
  normalize_audio: false,
  output_directory: null,
  filename_pattern: "clip",
  open_output_folder: true,
  keep_original: true,
};

interface Option<T> {
  id: T;
  name: string;
  description?: string;
}

export const LAYOUT_OPTIONS: readonly Option<VideoLayout>[] = [
  { id: "center_crop", name: "9:16 Zoom", description: "Preenche toda a tela." },
  { id: "blurred_4_3", name: "4:3 + Blur", description: "Mais conteúdo visível." },
  { id: "blurred_16_9", name: "16:9 + Blur", description: "Preserva o quadro inteiro." },
];

export const SUBTITLE_POSITION_OPTIONS: readonly Option<SubtitlePosition>[] = [
  { id: "top", name: "Superior" },
  { id: "center", name: "Centro" },
  { id: "bottom", name: "Inferior" },
];

export const SUBTITLE_STYLE_OPTIONS: readonly Option<SubtitleStyleName>[] = [
  { id: "bold", name: "Bold" },
  { id: "minimal", name: "Minimal" },
  { id: "outline", name: "Outline" },
];

export const QUALITY_OPTIONS: readonly Option<RenderQuality>[] = [
  { id: "fast", name: "Rápida" },
  { id: "balanced", name: "Equilibrada" },
  { id: "high", name: "Alta" },
];

export const FILENAME_OPTIONS: readonly Option<FilenamePattern>[] = [
  { id: "clip", name: "clip-001" },
  { id: "title", name: "titulo-001" },
];

export const FPS_OPTIONS: readonly Option<OutputFps>[] = [
  { id: "original", name: "Original" },
  { id: "30", name: "30" },
  { id: "60", name: "60" },
];

export const TEXT_COLOR_PRESETS = ["#FFFFFF", "#FFE066", "#7DF9A6", "#8AB4FF", "#FF8A8A"];
export const OUTLINE_COLOR_PRESETS = ["#000000", "#101010", "#1B1F3B", "#3A0B0B"];

export function layoutName(layout: VideoLayout): string {
  return LAYOUT_OPTIONS.find((option) => option.id === layout)?.name ?? layout;
}

/** Layouts que compõem o vídeo sobre um fundo desfocado. */
export function usesBackground(layout: VideoLayout): boolean {
  return layout !== "center_crop";
}

export function isValidDuration(value: number): value is ClipDuration {
  return (CLIP_DURATION_OPTIONS as readonly number[]).includes(value);
}

/** O slider trabalha por índice: a lista não é uma progressão regular. */
export function durationIndex(value: number): number {
  const index = CLIP_DURATION_OPTIONS.indexOf(value as ClipDuration);
  return index >= 0 ? index : CLIP_DURATION_OPTIONS.indexOf(90);
}

export function durationAtIndex(index: number): ClipDuration {
  const bounded = Math.min(Math.max(Math.round(index), 0), CLIP_DURATION_OPTIONS.length - 1);
  return CLIP_DURATION_OPTIONS[bounded] ?? 90;
}

function clamp(value: number, min: number, max: number, fallback: number): number {
  if (!Number.isFinite(value)) return fallback;
  return Math.min(Math.max(Math.round(value), min), max);
}

const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;

function color(value: string, fallback: string): string {
  return HEX_COLOR.test(value) ? value.toUpperCase() : fallback;
}

function oneOf<T extends string>(
  value: string,
  options: readonly Option<T>[],
  fallback: T,
): T {
  return options.some((option) => option.id === value) ? (value as T) : fallback;
}

/**
 * Normaliza tudo antes de sair da máquina.
 *
 * O backend valida de novo e devolve 422; normalizar aqui evita mandar uma
 * requisição que já se sabe inválida.
 */
export function normalizeSettings(settings: VideoSettings): VideoSettings {
  const defaults = DEFAULT_SETTINGS;
  return {
    version: defaults.version,
    clip_duration_seconds: isValidDuration(settings.clip_duration_seconds)
      ? settings.clip_duration_seconds
      : settings.clip_duration_seconds > 180 ? 180 : defaults.clip_duration_seconds,
    layout: oneOf(settings.layout, LAYOUT_OPTIONS, defaults.layout),
    blur_strength: clamp(settings.blur_strength, 0, 100, defaults.blur_strength),
    background_darkness: clamp(
      settings.background_darkness,
      0,
      100,
      defaults.background_darkness,
    ),
    foreground_scale: clamp(
      settings.foreground_scale,
      FOREGROUND_SCALE_MIN,
      FOREGROUND_SCALE_MAX,
      defaults.foreground_scale,
    ),
    subtitles_enabled: Boolean(settings.subtitles_enabled),
    subtitle_font_size: clamp(
      settings.subtitle_font_size,
      SUBTITLE_FONT_SIZE_MIN,
      SUBTITLE_FONT_SIZE_MAX,
      defaults.subtitle_font_size,
    ),
    subtitle_position: oneOf(
      settings.subtitle_position,
      SUBTITLE_POSITION_OPTIONS,
      defaults.subtitle_position,
    ),
    subtitle_vertical_offset: clamp(
      settings.subtitle_vertical_offset,
      -SUBTITLE_OFFSET_LIMIT,
      SUBTITLE_OFFSET_LIMIT,
      0,
    ),
    subtitle_style: oneOf(
      settings.subtitle_style,
      SUBTITLE_STYLE_OPTIONS,
      defaults.subtitle_style,
    ),
    subtitle_text_color: color(settings.subtitle_text_color, defaults.subtitle_text_color),
    subtitle_outline_color: color(
      settings.subtitle_outline_color,
      defaults.subtitle_outline_color,
    ),
    render_quality: oneOf(settings.render_quality, QUALITY_OPTIONS, defaults.render_quality),
    output_fps: oneOf(settings.output_fps, FPS_OPTIONS, defaults.output_fps),
    volume: clamp(settings.volume, 0, 100, defaults.volume),
    normalize_audio: Boolean(settings.normalize_audio),
    // Só um caminho absoluto vindo do diálogo nativo chega ao backend.
    output_directory: settings.output_directory?.trim() ? settings.output_directory : null,
    filename_pattern: oneOf(
      settings.filename_pattern,
      FILENAME_OPTIONS,
      defaults.filename_pattern,
    ),
    open_output_folder: Boolean(settings.open_output_folder),
    keep_original: Boolean(settings.keep_original),
  };
}

export interface CreateVideoPayload {
  url: string;
  settings: VideoSettings;
}

export interface CreateBatchPayload {
  urls: string[];
  settings: VideoSettings;
}

export function buildCreatePayload(url: string, settings: VideoSettings): CreateVideoPayload {
  return { url: url.trim(), settings: normalizeSettings(settings) };
}

/** Um snapshot só, aplicado a todos os vídeos do envio. */
export function buildBatchPayload(urls: string[], settings: VideoSettings): CreateBatchPayload {
  return { urls: urls.map((url) => url.trim()), settings: normalizeSettings(settings) };
}

export function styleName(style: SubtitleStyleName): string {
  return SUBTITLE_STYLE_OPTIONS.find((option) => option.id === style)?.name ?? style;
}

export interface SummaryItem {
  label: string;
  /** Presente só no item que representa a cor da legenda. */
  color?: string;
}

/**
 * Resumo curto para a Home: duração, layout e legenda.
 *
 * Legenda desligada colapsa em um item só — mostrar tamanho e cor de algo que
 * não vai aparecer seria ruído.
 */
export function summaryItems(settings: VideoSettings): SummaryItem[] {
  const items: SummaryItem[] = [
    { label: `${settings.clip_duration_seconds}s` },
    { label: layoutName(settings.layout) },
  ];

  if (!settings.subtitles_enabled) {
    items.push({ label: "Sem legendas" });
    return items;
  }

  items.push({ label: `${styleName(settings.subtitle_style)} ${settings.subtitle_font_size}px` });
  items.push({ label: "Cor", color: settings.subtitle_text_color });
  return items;
}
