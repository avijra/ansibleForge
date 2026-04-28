import { useCallback, useEffect, useState } from "react";
import { api } from "@/api/client";
import type { HealthResponse } from "@/api/types";

export function useHealth(intervalMs = 30_000) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

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
    const id = setInterval(check, intervalMs);
    return () => clearInterval(id);
  }, [check, intervalMs]);

  return { health, error, refresh: check };
}
