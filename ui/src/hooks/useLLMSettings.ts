import { useCallback, useEffect, useState } from "react";
import { api } from "@/api/client";
import type { LLMSettings, LLMSettingsUpdate } from "@/api/types";

export function useLLMSettings() {
  const [settings, setSettings] = useState<LLMSettings | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.llmSettings.get();
      setSettings(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load settings");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const update = useCallback(
    async (patch: LLMSettingsUpdate) => {
      setLoading(true);
      setError(null);
      try {
        const data = await api.llmSettings.update(patch);
        setSettings(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to update settings");
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
      const data = await api.llmSettings.reset();
      setSettings(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset settings");
    } finally {
      setLoading(false);
    }
  }, []);

  return { settings, loading, error, update, reset, refresh };
}
