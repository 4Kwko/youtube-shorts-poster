import { describe, expect, it } from "vitest";

import { DEFAULT_SETTINGS } from "./settings";
import { stageStates } from "./stages";
import type { Video, VideoStatus } from "./types";
import { isFinished, isTerminal } from "./types";

function video(status: VideoStatus, currentStage: string | null = null): Video {
  return {
    id: "v1",
    source_url: "https://www.youtube.com/watch?v=abc",
    source_type: "remote",
    provider: "youtube",
    title: null,
    duration: null,
    width: null,
    height: null,
    status,
    settings: DEFAULT_SETTINGS,
    progress: 0,
    current_stage: currentStage,
    error_code: null,
    error_message: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

describe("stageStates", () => {
  it("marca a importação como atual enquanto o download acontece", () => {
    const states = stageStates(video("downloading"));
    expect(states.importing).toBe("current");
    expect(states.transcribing).toBe("pending");
  });

  it("avança para transcrição quando o download termina", () => {
    const states = stageStates(video("downloaded"));
    expect(states.importing).toBe("done");
    expect(states.transcribing).toBe("current");
  });

  it("usa current_stage para desempatar o status processing", () => {
    expect(stageStates(video("processing", "clipping 2/5")).clipping).toBe("current");
    expect(stageStates(video("processing", "rendering 1/3")).rendering).toBe("current");
  });

  it("conclui todas as etapas quando renderizado", () => {
    const states = stageStates(video("rendered"));
    expect(Object.values(states).every((state) => state === "done")).toBe(true);
  });

  it("marca falha em todas as etapas", () => {
    expect(stageStates(video("failed")).importing).toBe("failed");
  });
});

describe("isTerminal", () => {
  it.each<[VideoStatus, boolean]>([
    ["exported", true],
    ["failed", true],
    ["cancelled", true],
    ["downloading", false],
    ["processing", false],
  ])("%s -> %s", (status, expected) => {
    expect(isTerminal(status)).toBe(expected);
  });
});

describe("isFinished", () => {
  it("rendered encerra o acompanhamento quando não há exportação", () => {
    const done = video("rendered");
    expect(isFinished(done)).toBe(true);
  });

  it("com pasta escolhida, rendered ainda espera a cópia", () => {
    const pending = video("rendered");
    pending.settings = { ...pending.settings, output_directory: "D:\\Videos\\Clipper" };
    expect(isFinished(pending)).toBe(false);
    expect(isFinished({ ...pending, status: "exported" })).toBe(true);
  });
});
