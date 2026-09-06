/**
 * Download do render final.
 *
 * O atributo `download` de `<a>` é ignorado em URL de outra origem, e o
 * backend roda em `127.0.0.1:8000` enquanto o app vive em `tauri://localhost`.
 * Dentro do Tauri, abrir no navegador padrão é o caminho que respeita o
 * `Content-Disposition: attachment` já enviado pelo backend. No navegador puro,
 * o `<a>` continua servindo.
 */

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function downloadFile(url: string): Promise<void> {
  if (isTauri()) {
    const { openUrl } = await import("@tauri-apps/plugin-opener");
    await openUrl(url);
    return;
  }

  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.rel = "noopener";
  anchor.click();
}
