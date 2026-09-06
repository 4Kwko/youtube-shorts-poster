import { describe, expect, it } from "vitest";

import {
  FILTER_OPTIONS,
  formatVideoDuration,
  humanDate,
  matchesFilter,
  matchesSearch,
  statusLabel,
} from "./format";
import type { VideoStatus } from "./types";

describe("statusLabel", () => {
  it.each<[VideoStatus, string]>([
    ["queued", "Na fila"],
    ["downloading", "Baixando"],
    ["transcribing", "Transcrevendo"],
    ["processing", "Criando clips"],
    ["clipped", "Criando clips"],
    ["exporting", "Exportando"],
    ["exported", "Concluído"],
    ["failed", "Falhou"],
  ])("%s vira %s", (status, label) => {
    expect(statusLabel(status)).toBe(label);
  });

  it("nunca mostra o enum cru", () => {
    const statuses: VideoStatus[] = ["pending", "downloaded", "rendered", "cancelled"];
    for (const status of statuses) {
      expect(statusLabel(status)).not.toBe(status);
    }
  });
});

describe("matchesFilter", () => {
  it("todos passa em qualquer status", () => {
    expect(matchesFilter("failed", "all")).toBe(true);
  });

  it("concluídos cobre rendered e exported", () => {
    expect(matchesFilter("rendered", "done")).toBe(true);
    expect(matchesFilter("exported", "done")).toBe(true);
    expect(matchesFilter("downloading", "done")).toBe(false);
  });

  it("processando exclui terminados e falhos", () => {
    expect(matchesFilter("downloading", "processing")).toBe(true);
    expect(matchesFilter("exported", "processing")).toBe(false);
    expect(matchesFilter("failed", "processing")).toBe(false);
  });

  it("falharam cobre failed e cancelled", () => {
    expect(matchesFilter("failed", "failed")).toBe(true);
    expect(matchesFilter("cancelled", "failed")).toBe(true);
  });

  it("oferece quatro filtros", () => {
    expect(FILTER_OPTIONS.map((option) => option.id)).toEqual([
      "all",
      "processing",
      "done",
      "failed",
    ]);
  });
});

describe("matchesSearch", () => {
  it("busca vazia aceita tudo", () => {
    expect(matchesSearch(null, "https://x", "  ")).toBe(true);
  });

  it("ignora maiúsculas e procura no título e na URL", () => {
    expect(matchesSearch("Tournament Highlights", "https://x", "tourna")).toBe(true);
    expect(matchesSearch(null, "https://youtu.be/abc", "youtu")).toBe(true);
    expect(matchesSearch("Outro", "https://x", "tourna")).toBe(false);
  });
});

describe("humanDate", () => {
  const now = new Date(2026, 8, 5, 18, 0);

  it("mostra a hora quando é hoje", () => {
    expect(humanDate(new Date(2026, 8, 5, 17, 42).toISOString(), now)).toBe("Hoje, 17:42");
  });

  it("mostra ontem", () => {
    expect(humanDate(new Date(2026, 8, 4, 22, 10).toISOString(), now)).toBe("Ontem, 22:10");
  });

  it("mostra a data completa quando é mais antigo", () => {
    expect(humanDate(new Date(2026, 8, 3, 9, 5).toISOString(), now)).toBe("03/09/2026");
  });

  it("tolera data inválida", () => {
    expect(humanDate("não é data", now)).toBe("—");
  });
});

describe("formatVideoDuration", () => {
  it.each<[number | null, string]>([
    [null, "—"],
    [0, "—"],
    [95, "01:35"],
    [2538, "42:18"],
    [3661, "1:01:01"],
  ])("%s segundos vira %s", (seconds, expected) => {
    expect(formatVideoDuration(seconds)).toBe(expected);
  });
});
