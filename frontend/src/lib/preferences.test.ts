import { beforeEach, describe, expect, it } from "vitest";

import { clearSettings, loadSettings, saveSettings, shortenPath } from "./preferences";
import { DEFAULT_SETTINGS } from "./settings";

describe("preferências do app", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("começa nos defaults oficiais", () => {
    expect(loadSettings()).toEqual(DEFAULT_SETTINGS);
  });

  it("sobrevive entre execuções", () => {
    const chosen = {
      ...DEFAULT_SETTINGS,
      clip_duration_seconds: 120,
      layout: "blurred_16_9" as const,
      subtitle_font_size: 96,
      output_directory: "D:\\Videos\\Clipper",
      keep_original: false,
    };

    saveSettings(chosen);

    expect(loadSettings()).toEqual(chosen);
  });

  it("restaurar padrões limpa o que estava salvo", () => {
    saveSettings({ ...DEFAULT_SETTINGS, volume: 20 });
    clearSettings();

    expect(loadSettings()).toEqual(DEFAULT_SETTINGS);
  });

  it("completa campos ausentes de uma versão anterior", () => {
    localStorage.setItem(
      "clipper.settings.v2",
      JSON.stringify({ clip_duration_seconds: 120 }),
    );

    const loaded = loadSettings();

    expect(loaded.clip_duration_seconds).toBe(120);
    expect(loaded.subtitle_font_size).toBe(DEFAULT_SETTINGS.subtitle_font_size);
  });

  it("normaliza valor corrompido em vez de quebrar a Home", () => {
    localStorage.setItem("clipper.settings.v2", "{não é json");
    expect(loadSettings()).toEqual(DEFAULT_SETTINGS);

    localStorage.setItem(
      "clipper.settings.v2",
      JSON.stringify({ clip_duration_seconds: 7, volume: 500, layout: "fullscreen" }),
    );
    const loaded = loadSettings();
    expect(loaded.clip_duration_seconds).toBe(90);
    expect(loaded.volume).toBe(100);
    expect(loaded.layout).toBe("blurred_4_3");
  });
});

describe("shortenPath", () => {
  it("mostra o caminho inteiro quando cabe", () => {
    expect(shortenPath("D:\\Videos\\Clipper")).toBe("D:\\Videos\\Clipper");
  });

  it("trunca pela esquerda, preservando o fim", () => {
    const short = shortenPath("D:\\Users\\alguem\\Videos\\Projetos\\Clipper\\Saida", 20);
    expect(short.length).toBeLessThanOrEqual(20);
    expect(short.endsWith("Saida")).toBe(true);
  });

  it("diz quando não há pasta", () => {
    expect(shortenPath(null)).toBe("Não definida");
  });
});
