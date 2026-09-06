/** Contratos da API do motor local. Espelham os schemas do backend. */

import type { VideoSettings } from "./settings";

export type VideoStatus =
  | "pending"
  | "queued"
  | "downloading"
  | "downloaded"
  | "transcribing"
  | "transcribed"
  | "processing"
  | "clipped"
  | "rendered"
  | "exporting"
  | "exported"
  | "completed"
  | "failed"
  | "cancelled";

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export type JobType =
  | "ingest"
  | "transcribe"
  | "clip"
  | "render"
  | "export"
  | "full_pipeline";

export type ClipStatus = "pending" | "rendering" | "rendered" | "failed";

export interface Health {
  status: string;
  name: string;
  version: string;
  environment: string;
  uptime_seconds: number;
  dependencies: { ffmpeg: boolean; ffprobe: boolean };
}

export type SourceType = "remote" | "local";

export interface Video {
  id: string;
  source_url: string | null;
  source_type: SourceType;
  provider: string;
  title: string | null;
  duration: number | null;
  width: number | null;
  height: number | null;
  status: VideoStatus;
  settings: VideoSettings;
  progress: number;
  current_stage: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface Job {
  id: string;
  job_type: JobType;
  status: JobStatus;
  attempt: number;
  max_attempts: number;
  progress: number;
  current_stage: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Clip {
  id: string;
  video_id: string;
  sequence: number;
  start_time: number;
  end_time: number;
  duration: number;
  status: ClipStatus;
  created_at: string;
  updated_at: string;
  media_url: string | null;
  download_url: string | null;
}

/** Envelope de erro do backend. */
export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown> };
  request_id: string | null;
}

/** Estados terminais: o polling para em qualquer um deles. */
export const TERMINAL_VIDEO_STATUSES: readonly VideoStatus[] = [
  "exported",
  "completed",
  "failed",
  "cancelled",
];

export function isTerminal(status: VideoStatus): boolean {
  return TERMINAL_VIDEO_STATUSES.includes(status);
}

/**
 * `rendered` só encerra o acompanhamento quando não há exportação pendente:
 * com pasta escolhida, ainda falta copiar os arquivos.
 */
export function isFinished(video: Video): boolean {
  if (video.status === "rendered") return !video.settings.output_directory;
  return isTerminal(video.status);
}

/** Telas de resultado: os clips já existem, mesmo que a cópia siga em curso. */
export function hasClips(status: VideoStatus): boolean {
  return status === "rendered" || status === "exported" || status === "completed";
}

export interface VideoSummary {
  id: string;
  source_url: string | null;
  source_type: SourceType;
  provider: string;
  title: string | null;
  duration: number | null;
  status: VideoStatus;
  progress: number;
  current_stage: string | null;
  error_code: string | null;
  error_message: string | null;
  settings: VideoSettings;
  clip_count: number;
  has_thumbnail: boolean;
  created_at: string;
  updated_at: string;
}

export interface VideoListPage {
  items: VideoSummary[];
  total: number;
  limit: number;
  offset: number;
}
