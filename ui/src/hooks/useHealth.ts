import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/api/client";
import type { HealthResponse } from "@/api/types";

export function useHealth(intervalMs = 30_000) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const check = useCallback(async () => {
    try {
      const res = await api.health();
      setHealth(res);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Health check failed");
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
