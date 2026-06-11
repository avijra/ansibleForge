import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/api/client";
import type { ExecutionSettings, ExecutionSettingsUpdate } from "@/api/types";

export function useExecutionSettings() {
  const [settings, setSettings] = useState<ExecutionSettings | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const data = await api.executionSettings.get();
      setSettings(data);
      setError(null);
      return data;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load execution settings");
      return null;
    }
  }, []);

  const startPollingWhilePulling = useCallback(() => {
    stopPolling();
    pollRef.current = window.setInterval(async () => {
      const data = await refresh();
      if (
        !data ||
        data.image_pull_status === "ready" ||
        data.image_pull_status === "failed"
      ) {
        stopPolling();
      }
    }, 2000);
  }, [refresh, stopPolling]);

  useEffect(() => {
    refresh();
    return () => stopPolling();
  }, [refresh, stopPolling]);

  const update = useCallback(
    async (patch: ExecutionSettingsUpdate) => {
      setLoading(true);
      setError(null);
      try {
        const data = await api.executionSettings.update(patch);
        setSettings(data);
        if (data.enabled && data.image_pull_status === "pulling") {
          startPollingWhilePulling();
        }
        return data;
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to update execution settings");
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [startPollingWhilePulling],
  );

  const pull = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.executionSettings.pull();
      setSettings(data);
      if (data.image_pull_status === "pulling") {
        startPollingWhilePulling();
      }
      return data;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to pull execution image");
      throw err;
    } finally {
      setLoading(false);
    }
  }, [startPollingWhilePulling]);

  const testRemote = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      return await api.executionSettings.testRemote();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Remote connection test failed";
      setError(message);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

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

  return {
    settings,
    loading,
    error,
    update,
    pull,
    testRemote,
    reset,
    refresh,
    startPollingWhilePulling,
  };
}
