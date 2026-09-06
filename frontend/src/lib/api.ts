/**
 * Único ponto de contato com o motor local.
 *
 * Nenhum `fetch` fora daqui: assim a base URL, o tratamento do envelope de
 * erro e os timeouts existem em um lugar só.
 */

import type {
  CreateBatchPayload,
  CreateVideoPayload,
  VideoSettings,
} from "./settings";
import type {
  ApiErrorBody,
  Clip,
  Health,
  Job,
  Video,
  VideoListPage,
} from "./types";

const BASE_URL = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

const HEALTH_TIMEOUT_MS = 4000;
const REQUEST_TIMEOUT_MS = 15000;

/** Erro já tratado: `message` é seguro para exibir na interface. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(message: string, code: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

export function apiBaseUrl(): string {
  return BASE_URL;
}

export function mediaUrl(path: string): string {
  return `${BASE_URL}${path}`;
}

export function thumbnailUrl(videoId: string): string {
  return `${BASE_URL}/api/v1/videos/${videoId}/thumbnail`;
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== "object" || value === null) return false;
  const candidate = (value as { error?: unknown }).error;
  return typeof candidate === "object" && candidate !== null && "message" in candidate;
}

async function toApiError(response: Response): Promise<ApiError> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (isErrorBody(body)) {
    return new ApiError(body.error.message, body.error.code, response.status);
  }
  return new ApiError("O motor local respondeu com um erro.", "unexpected_error", response.status);
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs = REQUEST_TIMEOUT_MS,
  signal?: AbortSignal,
): Promise<T> {
  // Timeout próprio, combinado com o sinal de quem chamou (desmontagem etc.).
  const timeout = AbortSignal.timeout(timeoutMs);
  const composed = signal ? AbortSignal.any([signal, timeout]) : timeout;

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      signal: composed,
      headers: { "Content-Type": "application/json", ...init.headers },
    });
  } catch (error) {
    // Repassa cancelamento explícito; o resto vira "motor inacessível".
    if (signal?.aborted) throw error;
    throw new ApiError("Não foi possível falar com o motor local.", "network_error", 0);
  }

  if (!response.ok) throw await toApiError(response);
  return (await response.json()) as T;
}

export const api = {
  youtubeConnect(): Promise<{ started: boolean }> {
    return request("/api/v1/youtube/connect", { method: "POST", body: "{}" });
  },
  youtubeClient(content: string): Promise<{ saved: boolean }> {
    return request("/api/v1/youtube/client", { method: "PUT", body: JSON.stringify({ content }) });
  },
  youtubeSavePreferences(value: PublishingPreferences): Promise<PublishingPreferences> {
    return request("/api/v1/youtube/preferences", { method: "PUT", body: JSON.stringify(value) });
  },
  youtubeStatus(): Promise<{
    enabled: boolean; connected: boolean;
    configured: boolean; channel: string | null; channel_id: string;
    login_state: string; login_error: string | null; publishing_error: string | null;
    preferences: PublishingPreferences;
    uploads: { clip_id: string; title: string; state: string; youtube_id: string | null;
      actual_privacy: string | null; error: string | null }[];
  }> {
    return request("/api/v1/youtube/status", {}, REQUEST_TIMEOUT_MS);
  },
  health(signal?: AbortSignal): Promise<Health> {
    return request<Health>("/health", {}, HEALTH_TIMEOUT_MS, signal);
  },

  createVideo(payload: CreateVideoPayload, signal?: AbortSignal): Promise<Video> {
    return request<Video>(
      "/api/v1/videos",
      { method: "POST", body: JSON.stringify(payload) },
      REQUEST_TIMEOUT_MS,
      signal,
    );
  },

  listVideos(limit = 30, offset = 0, signal?: AbortSignal): Promise<VideoListPage> {
    return request<VideoListPage>(
      `/api/v1/videos?limit=${limit}&offset=${offset}`,
      {},
      REQUEST_TIMEOUT_MS,
      signal,
    );
  },

  retryVideo(videoId: string, signal?: AbortSignal): Promise<unknown> {
    return request<unknown>(
      `/api/v1/videos/${videoId}/retry`,
      { method: "POST" },
      REQUEST_TIMEOUT_MS,
      signal,
    );
  },

  async deleteVideo(videoId: string, signal?: AbortSignal): Promise<void> {
    // 204 sem corpo: `request` espera JSON, então a chamada é direta aqui.
    const response = await fetch(`${BASE_URL}/api/v1/videos/${videoId}`, {
      method: "DELETE",
      signal,
    });
    if (!response.ok) throw await toApiError(response);
  },

  createVideos(payload: CreateBatchPayload, signal?: AbortSignal): Promise<{ videos: Video[] }> {
    return request<{ videos: Video[] }>(
      "/api/v1/videos/batch",
      { method: "POST", body: JSON.stringify(payload) },
      REQUEST_TIMEOUT_MS,
      signal,
    );
  },

  createLocalVideos(
    payload: { paths: string[]; settings: VideoSettings },
    signal?: AbortSignal,
  ): Promise<{ videos: Video[] }> {
    return request<{ videos: Video[] }>(
      "/api/v1/videos/local",
      { method: "POST", body: JSON.stringify(payload) },
      REQUEST_TIMEOUT_MS,
      signal,
    );
  },

  getVideo(videoId: string, signal?: AbortSignal): Promise<Video> {
    return request<Video>(`/api/v1/videos/${videoId}`, {}, REQUEST_TIMEOUT_MS, signal);
  },

  listJobs(videoId: string, signal?: AbortSignal): Promise<Job[]> {
    return request<Job[]>(`/api/v1/videos/${videoId}/jobs`, {}, REQUEST_TIMEOUT_MS, signal);
  },

  listClips(videoId: string, signal?: AbortSignal): Promise<Clip[]> {
    return request<Clip[]>(`/api/v1/videos/${videoId}/clips`, {}, REQUEST_TIMEOUT_MS, signal);
  },
};

export interface PublishingPreferences {
  enabled: boolean;
  description: string;
  hashtags: string;
  privacy: "public" | "unlisted" | "private";
}
