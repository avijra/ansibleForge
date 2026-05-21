import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/api/client";
import type { HealthResponse } from "@/api/types";

const HEALTH_TIMEOUT_MS = 5_000;

export function useHealth(intervalMs = 30_000) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const check = useCallback(async () => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);
    try {
      const res = await api.health(controller.signal);
      setHealth(res);
      setError(null);
    } catch (err) {
      if (controller.signal.aborted) {
        setHealth(null);
        setError("Health check timed out — backend may be busy");
      } else {
        setHealth(null);
        setError(err instanceof Error ? err.message : "Health check failed");
      }
    } finally {
      clearTimeout(timer);
    }
  }, []);

  useEffect(() => {
    check();

    function start() {
      if (!intervalRef.current) {
        intervalRef.current = setInterval(check, intervalMs);
      }
    }

    function stop() {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    }

    function onVisibilityChange() {
      if (document.hidden) {
        stop();
      } else {
        check();
        start();
      }
    }

    start();
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [check, intervalMs]);

  return { health, error, refresh: check };
}
