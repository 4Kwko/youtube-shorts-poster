import { describe, expect, it } from "vitest";

import { NAV_ITEMS, VIEW_TITLES, resolveView } from "./navigation";

describe("resolveView", () => {
  it("sem vídeo em andamento, Home mostra a criação", () => {
    expect(resolveView({ nav: "home", videoId: null, status: null })).toBe("home");
  });

  it("vídeo criado leva para o processamento", () => {
    expect(resolveView({ nav: "home", videoId: "v1", status: null })).toBe("processing");
    expect(resolveView({ nav: "home", videoId: "v1", status: "downloading" })).toBe("processing");
    expect(resolveView({ nav: "home", videoId: "v1", status: "failed" })).toBe("processing");
  });

  it.each(["rendered", "completed"])("status %s leva para os resultados", (status) => {
    expect(resolveView({ nav: "home", videoId: "v1", status })).toBe("results");
  });

  it("Configurações nunca é interrompida por um vídeo em andamento", () => {
    expect(resolveView({ nav: "settings", videoId: "v1", status: "processing" })).toBe(
      "settings",
    );
  });

  it("um projeto reaberto ocupa a área principal sem sair da aba", () => {
    expect(resolveView({ nav: "projects", videoId: "v1", status: "processing" })).toBe(
      "processing",
    );
    expect(resolveView({ nav: "projects", videoId: "v1", status: "exported" })).toBe(
      "results",
    );
    expect(resolveView({ nav: "projects", videoId: null, status: null })).toBe("projects");
  });

  it("voltar para Home retoma o vídeo em andamento", () => {
    expect(resolveView({ nav: "home", videoId: "v1", status: "processing" })).toBe("processing");
  });
});

describe("navegação", () => {
  it("todo item da sidebar tem título de página", () => {
    for (const key of NAV_ITEMS) {
      expect(VIEW_TITLES[key]).toBeTruthy();
    }
    expect(VIEW_TITLES.processing).toBe("Processando");
    expect(VIEW_TITLES.results).toBe("Clips");
  });
});
