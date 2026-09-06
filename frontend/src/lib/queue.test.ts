import { describe, expect, it } from "vitest";

import {
  MAX_BATCH_VIDEOS,
  addFiles,
  addUrls,
  fileLabel,
  isValidUrl,
  parseUrls,
  partition,
  removeItem,
  shortenUrl,
  submitLabel,
} from "./queue";
import type { QueueItem } from "./queue";

const A = "https://www.youtube.com/watch?v=aaa";
const B = "https://www.youtube.com/watch?v=bbb";

function queueOf(...urls: string[]): QueueItem[] {
  return urls.map((url, index) => ({
    id: `item-${index}`,
    kind: "url" as const,
    value: url,
    label: url,
  }));
}

describe("isValidUrl", () => {
  it.each([A, "http://youtu.be/x"])("aceita %s", (url) => {
    expect(isValidUrl(url)).toBe(true);
  });

  it.each(["texto solto", "file:///etc/passwd", "", "   "])("recusa %s", (value) => {
    expect(isValidUrl(value)).toBe(false);
  });
});

describe("parseUrls", () => {
  it("separa por quebra de linha, espaço e tab", () => {
    expect(parseUrls(`${A}\n${B}`)).toEqual([A, B]);
    expect(parseUrls(`${A} ${B}`)).toEqual([A, B]);
    expect(parseUrls(`${A}\t${B}`)).toEqual([A, B]);
  });

  it("descarta o que não é URL", () => {
    expect(parseUrls(`${A} lixo ${B}`)).toEqual([A, B]);
    expect(parseUrls("nada aqui")).toEqual([]);
  });
});

describe("addUrls", () => {
  it("adiciona preservando a ordem de inserção", () => {
    const result = addUrls([], `${A}\n${B}`);

    expect(result.added).toBe(2);
    expect(result.items.map((item) => item.value)).toEqual([A, B]);
  });

  it("ignora duplicata dentro da fila", () => {
    const result = addUrls(queueOf(A), A);

    expect(result.added).toBe(0);
    expect(result.skipped).toBe(1);
    expect(result.items).toHaveLength(1);
  });

  it("não passa do limite", () => {
    const full = queueOf(
      ...Array.from({ length: MAX_BATCH_VIDEOS }, (_, index) => `https://youtu.be/v${index}`),
    );

    const result = addUrls(full, A);

    expect(result.items).toHaveLength(MAX_BATCH_VIDEOS);
    expect(result.skipped).toBe(1);
  });

  it("corta no limite ao colar mais do que cabe", () => {
    const many = Array.from({ length: 25 }, (_, index) => `https://youtu.be/x${index}`);

    const result = addUrls([], many.join("\n"));

    expect(result.items).toHaveLength(MAX_BATCH_VIDEOS);
    expect(result.added).toBe(MAX_BATCH_VIDEOS);
    expect(result.skipped).toBe(5);
  });

  it("texto inválido não muda a fila", () => {
    const current = queueOf(A);
    const result = addUrls(current, "não é link");

    expect(result.items).toBe(current);
    expect(result.added).toBe(0);
  });
});

describe("removeItem", () => {
  it("remove só o item pedido", () => {
    const current = queueOf(A, B);

    expect(removeItem(current, "item-0").map((item) => item.value)).toEqual([B]);
  });
});

describe("submitLabel", () => {
  it("mostra a quantidade quando há mais de um", () => {
    expect(submitLabel(0)).toBe("Gerar projeto");
    expect(submitLabel(1)).toBe("Gerar projeto");
    expect(submitLabel(3)).toBe("Gerar 3 projetos");
  });
});

describe("shortenUrl", () => {
  it("tira o esquema e trunca no meio", () => {
    expect(shortenUrl(A)).toBe("www.youtube.com/watch?v=aaa");

    const long = `https://www.youtube.com/watch?v=${"x".repeat(80)}`;
    const short = shortenUrl(long);
    expect(short.length).toBeLessThanOrEqual(47);
    expect(short).toContain("…");
  });
});

describe("arquivos locais", () => {
  it("entra na fila com o nome do arquivo como rótulo", () => {
    const result = addFiles([], ["D:\\Videos\\entrevista.mp4", "/home/eu/gameplay.mkv"]);

    expect(result.added).toBe(2);
    expect(result.items.map((item) => item.label)).toEqual([
      "entrevista.mp4",
      "gameplay.mkv",
    ]);
    expect(result.items.every((item) => item.kind === "file")).toBe(true);
  });

  it("ignora o mesmo arquivo repetido", () => {
    const first = addFiles([], ["D:\\Videos\\a.mp4"]);
    const second = addFiles(first.items, ["D:\\Videos\\a.mp4"]);

    expect(second.added).toBe(0);
    expect(second.skipped).toBe(1);
  });

  it("compartilha o limite com as URLs", () => {
    const urls = addUrls(
      [],
      Array.from({ length: 18 }, (_, index) => `https://youtu.be/v${index}`).join("\n"),
    );

    const mixed = addFiles(urls.items, ["/a.mp4", "/b.mp4", "/c.mp4"]);

    expect(mixed.items).toHaveLength(MAX_BATCH_VIDEOS);
    expect(mixed.added).toBe(2);
    expect(mixed.skipped).toBe(1);
  });

  it("separa a fila mista por destino", () => {
    const withUrl = addUrls([], A);
    const mixed = addFiles(withUrl.items, ["/videos/local.mp4"]);

    expect(partition(mixed.items)).toEqual({
      urls: [A],
      paths: ["/videos/local.mp4"],
    });
  });

  it("extrai o nome em caminho Windows e Unix", () => {
    expect(fileLabel("D:\\Meus Videos\\clipe final.mp4")).toBe("clipe final.mp4");
    expect(fileLabel("/home/eu/videos/clipe.mkv")).toBe("clipe.mkv");
  });
});
