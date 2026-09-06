import { describe, expect, it } from "vitest";

import type { EngineStatusPayload, EnginePhase } from "./engine";
import { ENGINE_LABELS, resolveEngineState } from "./engine";

function status(phase: EnginePhase, message: string | null = null): EngineStatusPayload {
  return { phase, message, port: 8000, reused: false };
}

describe("resolveEngineState", () => {
  it("health respondendo é sempre motor pronto", () => {
    expect(resolveEngineState(true, status("starting"))).toBe("ready");
    expect(resolveEngineState(true, null)).toBe("ready");
  });

  it.each<EnginePhase>(["idle", "migrating", "starting", "ready"])(
    "fase %s sem health ainda é inicialização",
    (phase) => {
      expect(resolveEngineState(false, status(phase))).toBe("starting");
    },
  );

  it("falha do processo vira motor indisponível", () => {
    expect(resolveEngineState(false, status("failed", "porta ocupada"))).toBe("offline");
  });

  it("fora do Tauri não há motor gerenciado para esperar", () => {
    expect(resolveEngineState(false, null)).toBe("offline");
  });
});

describe("ENGINE_LABELS", () => {
  it("distingue inicialização de falha", () => {
    expect(ENGINE_LABELS.starting).toBe("Iniciando motor…");
    expect(ENGINE_LABELS.ready).toBe("Motor pronto");
    expect(ENGINE_LABELS.offline).toBe("Falha ao iniciar motor");
  });
});
