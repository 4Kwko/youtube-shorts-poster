import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { YouTubePublishing } from "./YouTubePublishing";

vi.mock("../../lib/api", () => ({ api: {
  youtubeStatus: vi.fn(), youtubeConnect: vi.fn(), youtubeSavePreferences: vi.fn(),
  youtubeClient: vi.fn(),
} }));

let container: HTMLDivElement;
let root: Root;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.clearAllMocks();
  vi.mocked(api.youtubeStatus).mockResolvedValue({
    enabled: false, connected: false, configured: true, channel: null, channel_id: "channel",
    login_state: "idle", login_error: null, publishing_error: null,
    preferences: { enabled: false, description: "Legenda fixa", hashtags: "#Shorts", privacy: "public" },
    uploads: [{ clip_id: "clip", title: "Meu clipe", state: "uploaded", youtube_id: "abc",
      actual_privacy: "private", error: null }],
  });
  vi.mocked(api.youtubeConnect).mockResolvedValue({ started: true });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe("publicação de Shorts", () => {
  it("abre login e mostra links de Shorts", async () => {
    await act(async () => root.render(<YouTubePublishing />));
    const button = container.querySelector("button")!;
    expect(button.textContent).toBe("Entrar com Google");
    await act(async () => button.click());
    expect(api.youtubeConnect).toHaveBeenCalledOnce();
    expect(container.textContent).toContain("Conclua o login no navegador");
    expect(container.querySelector("a")?.href).toBe("https://www.youtube.com/shorts/abc");
  });

  it("salva publicação automática com descrição e hashtags", async () => {
    await act(async () => root.render(<YouTubePublishing />));
    await act(async () => (container.querySelector("input[type=checkbox]") as HTMLInputElement).click());
    await act(async () => container.querySelector("form")!.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    ));
    expect(api.youtubeSavePreferences).toHaveBeenCalledWith({
      enabled: true, description: "Legenda fixa", hashtags: "#Shorts", privacy: "public",
    });
  });
});
