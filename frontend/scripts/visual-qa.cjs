/* Browser regression checks. All API responses are isolated test fixtures.
 * Run against Vite with Playwright available on NODE_PATH. No videos are published.
 */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const output = path.resolve(__dirname, "../../storage/design-qa");
const url = process.env.SIGNALCUT_QA_URL || "http://127.0.0.1:1420";
const settings = {
  version: 1,
  clip_duration_seconds: 90,
  layout: "blurred_4_3",
  blur_strength: 40,
  background_darkness: 34,
  foreground_scale: 100,
  subtitles_enabled: true,
  subtitle_font_size: 72,
  subtitle_position: "bottom",
  subtitle_vertical_offset: 0,
  subtitle_style: "bold",
  subtitle_text_color: "#FFFFFF",
  subtitle_outline_color: "#000000",
  render_quality: "balanced",
  output_fps: "original",
  volume: 100,
  normalize_audio: false,
  output_directory: null,
  filename_pattern: "clip",
  open_output_folder: true,
  keep_original: true,
};
const A = "https://www.youtube.com/watch?v=sample-a";
const B = "https://youtu.be/sample-b";
const C = "https://youtu.be/sample-c";
const youtube = {
  enabled: true,
  connected: true,
  configured: true,
  channel: "Canal de teste",
  channel_id: "test",
  login_state: "connected",
  login_error: null,
  publishing_error: null,
  preferences: {
    enabled: true,
    description: "",
    hashtags: "#Shorts",
    privacy: "public",
  },
  uploads: [],
};
function video(id, source) {
  return {
    id,
    source_url: source,
    source_type: "remote",
    provider: "youtube",
    title: "Projeto de teste " + id,
    duration: 420,
    width: 1920,
    height: 1080,
    status: "processing",
    progress: 62,
    current_stage: "rendering 2/3",
    error_code: null,
    error_message: null,
    settings,
    clip_count: 3,
    has_thumbnail: false,
    created_at: "2026-09-06T12:00:00Z",
    updated_at: "2026-09-06T12:00:00Z",
  };
}
async function main() {
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    channel: process.env.SIGNALCUT_QA_BROWSER || "msedge",
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  const errors = [];
  const requests = [];
  let projects = [];
  let complete = false;
  let listFailure = false;
  page.on("pageerror", (e) => errors.push(e.message));
  await page.addInitScript(
    (s) => localStorage.setItem("clipper.settings.v2", JSON.stringify(s)),
    settings,
  );
  await page.route("http://127.0.0.1:8000/**", async (route) => {
    const req = route.request();
    const pathname = new URL(req.url()).pathname;
    const headers = {
      "access-control-allow-origin": "*",
      "access-control-allow-headers": "*",
      "access-control-allow-methods": "GET,POST,PUT,DELETE,OPTIONS",
    };
    if (req.method() === "OPTIONS")
      return route.fulfill({ status: 204, headers });
    let body;
    if (pathname === "/health")
      body = {
        status: "ok",
        name: "test",
        version: "0.1.0",
        dependencies: { ffmpeg: true, ffprobe: true },
      };
    else if (pathname === "/api/v1/youtube/status") body = youtube;
    else if (pathname === "/api/v1/videos/batch" && req.method() === "POST") {
      const payload = req.postDataJSON();
      requests.push({ pathname, payload });
      projects = payload.urls.map((source, index) =>
        video("test-" + index, source),
      );
      body = { videos: projects };
    } else if (pathname === "/api/v1/videos") {
      if (listFailure)
        return route.fulfill({
          status: 500,
          headers,
          json: {
            error: { code: "test", message: "Falha de conexão simulada" },
          },
        });
      body = { items: projects, total: projects.length, limit: 30, offset: 0 };
    } else if (pathname.endsWith("/clips"))
      body = complete
        ? [
            {
              id: "clip-1",
              video_id: "test-0",
              sequence: 0,
              start_time: 0,
              end_time: 90,
              duration: 90,
              status: "rendered",
              created_at: "",
              updated_at: "",
              media_url: null,
              download_url: null,
            },
          ]
        : [];
    else if (pathname.endsWith("/jobs")) body = [];
    else if (pathname.startsWith("/api/v1/videos/"))
      body = {
        ...projects[0],
        status: complete ? "completed" : "processing",
        progress: complete ? 100 : 62,
      };
    else
      throw new Error(
        "Unexpected API request: " + req.method() + " " + pathname,
      );
    await route.fulfill({ headers, json: body });
  });
  try {
    await page.goto(url);
    await page.getByText("Motor pronto", { exact: true }).waitFor();
    assert.equal(await page.title(), "SignalCut");
    const field = page.getByRole("textbox", {
      name: "Link do vídeo",
      exact: true,
    });
    const add = page.getByRole("button", {
      name: "Adicionar à fila",
      exact: true,
    });
    await field.fill("texto inválido");
    assert.equal(await add.isDisabled(), true);
    await field.press("Enter");
    await page
      .getByText("Informe um link http ou https.", { exact: true })
      .waitFor();
    await field.fill(A);
    await field.press("Enter");
    await page.getByText("1 / 20", { exact: true }).waitFor();
    await page.getByRole("button", { name: /Remover .* da fila/ }).click();
    await page.getByText("0 / 20", { exact: true }).waitFor();
    await field.fill("texto " + A + "\n" + B + "\t" + C);
    await add.click();
    await page.getByText("3 / 20", { exact: true }).waitFor();
    await field.fill(A);
    await add.click();
    await page.getByText(/1 item\(ns\) ignorado/).waitFor();
    assert.equal(await page.locator(".queue__item").count(), 3);
    for (const width of [1440, 1280, 1024, 768, 390]) {
      await page.setViewportSize({ width, height: width < 600 ? 844 : 1000 });
      assert.equal(
        await page.evaluate(() => {
          const el = document.querySelector(".content");
          return (
            document.documentElement.scrollWidth <= innerWidth &&
            el.scrollWidth <= el.clientWidth + 1
          );
        }),
        true,
        "Horizontal overflow at " + width,
      );
      await page.screenshot({
        path: path.join(output, "home-" + width + ".png"),
        fullPage: true,
        animations: "disabled",
      });
    }
    await page.emulateMedia({ reducedMotion: "reduce" });
    assert.ok(
      await page
        .locator(".content__inner")
        .evaluate(
          (el) => parseFloat(getComputedStyle(el).animationDuration) < 0.001,
        ),
    );
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page
      .getByRole("button", { name: "Limpar fila", exact: true })
      .click();
    await field.fill(
      Array.from({ length: 25 }, (_, i) => "https://youtu.be/limit-" + i).join(
        "\n",
      ),
    );
    await add.click();
    await page.getByText("20 / 20", { exact: true }).waitFor();
    assert.equal(await field.isDisabled(), true);
    assert.equal(await page.locator(".queue__item").count(), 20);
    await page
      .getByRole("button", { name: "Gerar 20 projetos", exact: true })
      .click();
    await page
      .getByRole("heading", { name: "Seus projetos", exact: true })
      .waitFor();
    assert.equal(requests[0].pathname, "/api/v1/videos/batch");
    assert.equal(requests[0].payload.urls.length, 20);
    assert.deepEqual(requests[0].payload.settings, settings);
    await page
      .getByRole("heading", { name: "Projeto de teste test-0", exact: true })
      .waitFor();
    await page.screenshot({
      path: path.join(output, "projects-desktop.png"),
      fullPage: true,
      animations: "disabled",
    });
    await page.getByRole("radio", { name: "Concluídos", exact: true }).click();
    await page
      .getByRole("heading", {
        name: "Nenhum resultado para este filtro.",
        exact: true,
      })
      .waitFor();
    await page.getByRole("radio", { name: "Todos", exact: true }).click();
    await page
      .getByRole("searchbox", { name: "Buscar projetos", exact: true })
      .fill("test-0");
    assert.equal(await page.locator(".project").count(), 1);
    await page
      .getByRole("searchbox", { name: "Buscar projetos", exact: true })
      .fill("");
    await page.locator('summary[aria-label="Mais ações"]').first().click();
    await page
      .getByRole("button", { name: "Excluir projeto", exact: true })
      .click();
    await page.getByRole("dialog").waitFor();
    await page.keyboard.press("Escape");
    assert.equal(await page.getByRole("dialog").count(), 0);
    await page
      .getByRole("button", { name: "Novo projeto", exact: true })
      .click();
    await field.fill(A);
    await field.press("Enter");
    await page
      .getByRole("button", { name: "Gerar projeto", exact: true })
      .click();
    await page
      .getByRole("heading", {
        name: "Seu vídeo está em produção.",
        exact: true,
      })
      .waitFor();
    assert.equal(requests[1].payload.urls.length, 1);
    await page
      .getByRole("progressbar", {
        name: "Progresso do processamento",
        exact: true,
      })
      .waitFor();
    await page.screenshot({
      path: path.join(output, "processing-desktop.png"),
      fullPage: true,
      animations: "disabled",
    });
    complete = true;
    await page
      .getByRole("heading", { name: "1 clipe pronto", exact: true })
      .waitFor({ timeout: 15000 });
    await page.screenshot({
      path: path.join(output, "results-desktop.png"),
      fullPage: true,
      animations: "disabled",
    });
    await page.getByRole("button", { name: "Voltar", exact: true }).click();
    await page
      .getByRole("button", { name: "Configurações", exact: true })
      .click();
    await page
      .getByRole("heading", { name: "Seu jeito de criar.", exact: true })
      .waitFor();
    await page.screenshot({
      path: path.join(output, "settings-desktop.png"),
      fullPage: true,
      animations: "disabled",
    });
    for (const width of [768, 390]) {
      await page.setViewportSize({ width, height: 900 });
      assert.equal(
        await page.evaluate(() => {
          const el = document.querySelector(".content");
          return el.scrollWidth <= el.clientWidth + 1;
        }),
        true,
        "Settings overflow at " + width,
      );
    }
    await page.getByText("Publicação no YouTube", { exact: true }).click();
    await page
      .getByRole("button", { name: "Reconectar YouTube", exact: true })
      .waitFor();
    await page.screenshot({
      path: path.join(output, "settings-mobile.png"),
      fullPage: true,
      animations: "disabled",
    });
    await page.setViewportSize({ width: 1440, height: 1000 });
    projects = [];
    await page.getByRole("button", { name: "Projetos", exact: true }).click();
    await page
      .getByRole("heading", { name: "Nenhum projeto ainda.", exact: true })
      .waitFor();
    await page.screenshot({
      path: path.join(output, "projects-empty.png"),
      fullPage: true,
      animations: "disabled",
    });
    await page
      .getByRole("button", { name: "Criar primeiro projeto", exact: true })
      .click();
    await field.waitFor();
    listFailure = true;
    await page.getByRole("button", { name: "Projetos", exact: true }).click();
    await page
      .getByRole("alert")
      .filter({ hasText: "Falha de conexão simulada" })
      .waitFor();
    assert.equal(
      await page
        .getByRole("heading", { name: "Nenhum projeto ainda.", exact: true })
        .count(),
      0,
    );
    assert.deepEqual(errors, []);
    console.log(
      "PASS: URL, Enter, multi-URL whitespace, invalid input, duplicates, removal, clear, 20 limit, single/batch API snapshots, navigation, filters, dialog keyboard, reduced motion and responsive widths.",
    );
    console.log("Screenshots: " + output);
  } finally {
    await browser.close();
  }
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
