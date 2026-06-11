import { useCallback, useEffect, useState } from "react";
import { api } from "@/api/client";
import type { ExecutionSettings, ExecutionSettingsUpdate } from "@/api/types";

export function useExecutionSettings() {
  const [settings, setSettings] = useState<ExecutionSettings | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.executionSettings.get();
      setSettings(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load execution settings");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const update = useCallback(
    async (patch: ExecutionSettingsUpdate) => {
      setLoading(true);
      setError(null);
      try {
        const data = await api.executionSettings.update(patch);
        setSettings(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to update execution settings");
        throw err;
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const reset = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.executionSettings.reset();
      setSettings(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset execution settings");
    } finally {
      setLoading(false);
    }
  }, []);

  return { settings, loading, error, update, reset, refresh };
}
