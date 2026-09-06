import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Porta fixa: o Tauri aponta para ela em devUrl, e o backend a lista no CORS.
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    watch: {
      // O Cargo reescreve os artefatos enquanto o app roda; observar essa
      // pasta faz o watcher do Vite morrer com EBUSY no Windows.
      ignored: ["**/src-tauri/**"],
    },
  },
  build: { outDir: "dist", target: "chrome110", sourcemap: false },
  // `localStorage` nos testes de preferências.
  test: { environment: "jsdom" },
});