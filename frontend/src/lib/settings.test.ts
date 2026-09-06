import { describe, expect, it } from "vitest";

import {
  CLIP_DURATION_OPTIONS,
  DEFAULT_SETTINGS,
  LAYOUT_OPTIONS,
  buildBatchPayload,
  buildCreatePayload,
  durationAtIndex,
  durationIndex,
  isValidDuration,
  layoutName,
  normalizeSettings,
  summaryItems,
  usesBackground,
} from "./settings";
import type { VideoSettings } from "./settings";

function withSettings(patch: Partial<VideoSettings>): VideoSettings {
  return { ...DEFAULT_SETTINGS, ...patch };
}

describe("defaults", () => {
  it("reproduzem o comportamento anterior às opções", () => {
    expect(DEFAULT_SETTINGS.clip_duration_seconds).toBe(90);
    expect(DEFAULT_SETTINGS.layout).toBe("blurred_4_3");
    expect(DEFAULT_SETTINGS.subtitles_enabled).toBe(true);
    expect(DEFAULT_SETTINGS.subtitle_font_size).toBe(72);
    expect(DEFAULT_SETTINGS.render_quality).toBe("balanced");
    expect(DEFAULT_SETTINGS.output_fps).toBe("original");
    expect(DEFAULT_SETTINGS.volume).toBe(100);
    expect(DEFAULT_SETTINGS.normalize_audio).toBe(false);
  });

  it("a lista de durações é a acordada com o backend", () => {
    expect([...CLIP_DURATION_OPTIONS]).toEqual([
      30, 60, 90, 120, 150, 180,
    ]);
  });
});

describe("duração por índice", () => {
  it("o primeiro índice é 30s e o último é 180s", () => {
    expect(durationAtIndex(0)).toBe(30);
    expect(durationAtIndex(CLIP_DURATION_OPTIONS.length - 1)).toBe(180);
  });

  it("o default 90s está no índice 2", () => {
    expect(durationIndex(90)).toBe(2);
    expect(durationAtIndex(2)).toBe(90);
  });

  it("índice fora da faixa é preso às pontas", () => {
    expect(durationAtIndex(-5)).toBe(30);
    expect(durationAtIndex(999)).toBe(180);
  });

  it("valor desconhecido cai no default em vez de sumir do slider", () => {
    expect(durationIndex(45)).toBe(2);
  });

  it("nenhum índice produz valor fora da lista", () => {
    for (let index = 0; index < CLIP_DURATION_OPTIONS.length; index += 1) {
      expect(isValidDuration(durationAtIndex(index))).toBe(true);
    }
  });
});

describe("normalizeSettings", () => {
  it("mantém uma seleção válida", () => {
    const settings = withSettings({
      clip_duration_seconds: 120,
      layout: "blurred_16_9",
      subtitle_font_size: 96,
      volume: 60,
    });

    expect(normalizeSettings(settings)).toEqual(settings);
  });

  it("prende sliders à faixa do backend", () => {
    const normalized = normalizeSettings(
      withSettings({
        blur_strength: 300,
        background_darkness: -20,
        foreground_scale: 10,
        subtitle_font_size: 999,
        subtitle_vertical_offset: 5000,
        volume: 400,
      }),
    );

    expect(normalized.blur_strength).toBe(100);
    expect(normalized.background_darkness).toBe(0);
    expect(normalized.foreground_scale).toBe(60);
    expect(normalized.subtitle_font_size).toBe(110);
    expect(normalized.subtitle_vertical_offset).toBe(400);
    expect(normalized.volume).toBe(100);
  });

  it("recusa duração, layout e enums fora da lista", () => {
    const normalized = normalizeSettings(
      withSettings({
        clip_duration_seconds: 45,
        layout: "fullscreen" as never,
        subtitle_style: "karaoke" as never,
        output_fps: "24" as never,
        render_quality: "ultra" as never,
      }),
    );

    expect(normalized.clip_duration_seconds).toBe(90);
    expect(normalized.layout).toBe("blurred_4_3");
    expect(normalized.subtitle_style).toBe("bold");
    expect(normalized.output_fps).toBe("original");
    expect(normalized.render_quality).toBe("balanced");
  });

  it("recusa cor que não seja #RRGGBB", () => {
    const normalized = normalizeSettings(
      withSettings({ subtitle_text_color: "vermelho", subtitle_outline_color: "#GGG" }),
    );

    expect(normalized.subtitle_text_color).toBe("#FFFFFF");
    expect(normalized.subtitle_outline_color).toBe("#000000");
  });
});

describe("buildCreatePayload", () => {
  it("envia url limpa e configuração normalizada", () => {
    const payload = buildCreatePayload("  https://youtu.be/abc  ", withSettings({ volume: 70 }));

    expect(payload.url).toBe("https://youtu.be/abc");
    expect(payload.settings.volume).toBe(70);
    expect(payload.settings.version).toBe(1);
  });

  it("nunca deixa valor inválido sair da máquina", () => {
    const payload = buildCreatePayload("https://youtu.be/abc", {
      ...DEFAULT_SETTINGS,
      clip_duration_seconds: 7,
      blur_strength: 900,
    });

    expect(isValidDuration(payload.settings.clip_duration_seconds)).toBe(true);
    expect(payload.settings.blur_strength).toBe(100);
  });
});

describe("controles condicionais", () => {
  it("center_crop não compõe fundo desfocado", () => {
    expect(usesBackground("center_crop")).toBe(false);
    expect(usesBackground("blurred_4_3")).toBe(true);
    expect(usesBackground("blurred_16_9")).toBe(true);
  });

  it("os três layouts têm rótulo de interface", () => {
    expect(LAYOUT_OPTIONS.map((option) => option.id)).toEqual([
      "center_crop",
      "blurred_4_3",
      "blurred_16_9",
    ]);
    expect(layoutName("blurred_16_9")).toBe("16:9 + Blur");
  });
});

describe("summaryItems", () => {
  it("mostra duração, layout, estilo/tamanho e a cor da legenda", () => {
    expect(summaryItems(DEFAULT_SETTINGS)).toEqual([
      { label: "90s" },
      { label: "4:3 + Blur" },
      { label: "Bold 72px" },
      { label: "Cor", color: "#FFFFFF" },
    ]);
  });

  it("colapsa em um item quando a legenda está desligada", () => {
    expect(summaryItems(withSettings({ subtitles_enabled: false }))).toEqual([
      { label: "90s" },
      { label: "4:3 + Blur" },
      { label: "Sem legendas" },
    ]);
  });

  it("acompanha o estilo escolhido", () => {
    const items = summaryItems(
      withSettings({ subtitle_style: "outline", subtitle_font_size: 96 }),
    );
    expect(items[2]).toEqual({ label: "Outline 96px" });
  });
});

describe("snapshot ao gerar clips", () => {
  it("o payload leva as configurações do momento do clique", () => {
    const atClick = withSettings({ clip_duration_seconds: 120, volume: 40 });
    const payload = buildCreatePayload("https://youtu.be/abc", atClick);

    // Mudar as preferências depois não altera o payload já montado.
    const laterChanges = withSettings({ clip_duration_seconds: 30, volume: 100 });
    expect(laterChanges.clip_duration_seconds).toBe(30);

    expect(payload.settings.clip_duration_seconds).toBe(120);
    expect(payload.settings.volume).toBe(40);
  });
});

describe("buildBatchPayload", () => {
  it("um snapshot só para todas as URLs", () => {
    const payload = buildBatchPayload(
      ["  https://youtu.be/a  ", "https://youtu.be/b"],
      withSettings({ clip_duration_seconds: 120, layout: "blurred_16_9" }),
    );

    expect(payload.urls).toEqual(["https://youtu.be/a", "https://youtu.be/b"]);
    expect(payload.settings.clip_duration_seconds).toBe(120);
    expect(payload.settings.layout).toBe("blurred_16_9");
  });

  it("normaliza antes de enviar, como no envio único", () => {
    const payload = buildBatchPayload(
      ["https://youtu.be/a"],
      withSettings({ clip_duration_seconds: 45, volume: 900 }),
    );

    expect(payload.settings.clip_duration_seconds).toBe(90);
    expect(payload.settings.volume).toBe(100);
  });
});
