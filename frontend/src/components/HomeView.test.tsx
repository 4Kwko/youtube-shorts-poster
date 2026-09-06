import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { Simulate } from "react-dom/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HomeView } from "./HomeView";
import { chooseVideoFiles } from "../lib/preferences";
import { DEFAULT_SETTINGS } from "../lib/settings";
import { partition } from "../lib/queue";

vi.mock("../lib/preferences", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/preferences")>();
  return { ...actual, chooseVideoFiles: vi.fn() };
});
let root: Root;
let container: HTMLDivElement;
const submit = vi.fn();
async function render(disabled = false, submitting = false) {
  await act(async () =>
    root.render(
      <HomeView
        settings={DEFAULT_SETTINGS}
        disabled={disabled}
        submitting={submitting}
        error={null}
        onSubmit={submit}
        onEditSettings={vi.fn()}
      />,
    ),
  );
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.clearAllMocks();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe("Home: importação e estados de interação", () => {
  it("preserva fila mista e seus valores para envio", async () => {
    vi.mocked(chooseVideoFiles).mockResolvedValue(["D:/Videos/entrevista.mp4"]);
    await render();
    const input = container.querySelector("textarea")!;
    await act(async () => {
      input.value = "https://youtu.be/test";
      Simulate.change(input);
    });
    await act(async () => Simulate.keyDown(input, { key: "Enter" }));
    await act(async () =>
      container.querySelectorAll<HTMLButtonElement>("[role=radio]")[1]!.click(),
    );
    await act(async () =>
      container.querySelector<HTMLButtonElement>(".home__picker")!.click(),
    );
    expect(container.querySelectorAll(".queue__item")).toHaveLength(2);
    await act(async () =>
      container.querySelector<HTMLButtonElement>(".creator__submit")!.click(),
    );
    expect(partition(submit.mock.calls[0]![0])).toEqual({
      urls: ["https://youtu.be/test"],
      paths: ["D:/Videos/entrevista.mp4"],
    });
  });
  it("cancelar seleção não cria itens", async () => {
    vi.mocked(chooseVideoFiles).mockResolvedValue([]);
    await render();
    await act(async () =>
      container.querySelectorAll<HTMLButtonElement>("[role=radio]")[1]!.click(),
    );
    await act(async () =>
      container.querySelector<HTMLButtonElement>(".home__picker")!.click(),
    );
    expect(container.querySelectorAll(".queue__item")).toHaveLength(0);
    expect(
      container.querySelector<HTMLButtonElement>(".creator__submit")!.disabled,
    ).toBe(true);
  });
  it("bloqueia gerar sem motor e bloqueia edições enquanto envia", async () => {
    await render();
    const input = container.querySelector("textarea")!;
    await act(async () => {
      input.value = "https://youtu.be/test";
      Simulate.change(input);
    });
    await act(async () => Simulate.keyDown(input, { key: "Enter" }));
    await render(true);
    expect(
      container.querySelector<HTMLButtonElement>(".creator__submit")!.disabled,
    ).toBe(true);
    await render(false, true);
    expect(
      container.querySelector<HTMLTextAreaElement>("textarea")!.disabled,
    ).toBe(true);
    expect(
      container.querySelector<HTMLButtonElement>(".queue__clear")!.disabled,
    ).toBe(true);
    expect(
      container
        .querySelector<HTMLButtonElement>(".creator__submit")!
        .getAttribute("aria-busy"),
    ).toBe("true");
    expect(submit).not.toHaveBeenCalled();
  });
});
