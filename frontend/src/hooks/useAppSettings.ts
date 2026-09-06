import { useCallback, useEffect, useState } from "react";

import { clearSettings, defaultOutputDirectory, loadSettings, saveSettings } from "../lib/preferences";
import { DEFAULT_SETTINGS } from "../lib/settings";
import type { VideoSettings } from "../lib/settings";

/**
 * Defaults do app, editados na aba Configurações.
 *
 * Cada alteração é persistida na hora: não há botão Salvar, e fechar o app no
 * meio de um ajuste não perde a escolha.
 */
export function useAppSettings() {
  const [settings, setSettings] = useState<VideoSettings>(() => loadSettings());

  const update = useCallback((next: VideoSettings) => {
    setSettings(next);
    saveSettings(next);
  }, []);

  const reset = useCallback(() => {
    clearSettings();
    setSettings(DEFAULT_SETTINGS);
  }, []);

  // Sem pasta escolhida ainda: sugere Videos\SignalCut do próprio usuário.
  useEffect(() => {
    if (settings.output_directory) return;
    let active = true;
    void defaultOutputDirectory().then((directory) => {
      if (!active || !directory) return;
      setSettings((current) => {
        if (current.output_directory) return current;
        const next = { ...current, output_directory: directory };
        saveSettings(next);
        return next;
      });
    });
    return () => {
      active = false;
    };
    // Só na montagem: depois disso a pasta é escolha do usuário.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { settings, update, reset };
}
