import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import type { EngineState } from "../lib/engine";
import { getEngineStatus, resolveEngineState } from "../lib/engine";
import type { Health } from "../lib/types";

/** Enquanto o motor sobe, reconsulta; sem Tauri, uma tentativa basta. */
const STARTUP_RETRY_MS = 1200;

export function useBackendHealth() {
  const [state, setState] = useState<EngineState>("checking");
  const [health, setHealth] = useState<Health | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const check = useCallback(async (signal?: AbortSignal) => {
    if (timer.current) clearTimeout(timer.current);

    try {
      const result = await api.health(signal);
      setHealth(result);
      setMessage(null);
      setState("ready");
      return;
    } catch {
      if (signal?.aborted) return;
    }

    const status = await getEngineStatus().catch(() => null);
    if (signal?.aborted) return;

    const next = resolveEngineState(false, status);
    setHealth(null);
    setMessage(status?.message ?? null);
    setState(next);

    if (next === "starting") {
      timer.current = setTimeout(() => void check(signal), STARTUP_RETRY_MS);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void check(controller.signal);
    return () => {
      controller.abort();
      if (timer.current) clearTimeout(timer.current);
    };
  }, [check]);

  const retry = useCallback(() => {
    setState("checking");
    void check();
  }, [check]);

  return { state, health, message, retry };
}
