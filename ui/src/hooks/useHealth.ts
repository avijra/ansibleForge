import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/api/client";
import type { HealthResponse } from "@/api/types";

const HEALTH_TIMEOUT_MS = 5_000;
const STARTUP_RETRY_MS = 2_000;
const STARTUP_MAX_RETRIES = 15;

export function useHealth(intervalMs = 30_000) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(true);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startupRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryCount = useRef(0);

  const check = useCallback(async (): Promise<boolean> => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);
    try {
      const res = await api.health(controller.signal);
      setHealth(res);
      setError(null);
      setStarting(false);
      return true;
    } catch (err) {
      if (controller.signal.aborted) {
        setHealth(null);
        setError("Health check timed out — backend may be busy");
      } else {
        setHealth(null);
        setError(err instanceof Error ? err.message : "Health check failed");
      }
      return false;
    } finally {
      clearTimeout(timer);
    }
  }, []);

  useEffect(() => {
    let mounted = true;

    async function startupLoop() {
      const ok = await check();
      if (ok || !mounted) {
        if (mounted) startSteadyState();
        return;
      }
      retryCount.current += 1;
      if (retryCount.current >= STARTUP_MAX_RETRIES) {
        if (mounted) {
          setStarting(false);
          startSteadyState();
        }
        return;
      }
      if (mounted) {
        startupRef.current = setTimeout(startupLoop, STARTUP_RETRY_MS);
      }
    }

    function startSteadyState() {
      if (!intervalRef.current) {
        intervalRef.current = setInterval(check, intervalMs);
      }
    }

    function stopAll() {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      if (startupRef.current) {
        clearTimeout(startupRef.current);
        startupRef.current = null;
      }
    }

    function onVisibilityChange() {
      if (document.hidden) {
        stopAll();
      } else {
        check();
        startSteadyState();
      }
    }

    startupLoop();
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      mounted = false;
      stopAll();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [check, intervalMs]);

  return { health, error, starting, refresh: check };
}
