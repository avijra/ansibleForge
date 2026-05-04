import { useCallback, useEffect, useState } from "react";

export interface UpdateStatus {
  status: "idle" | "downloading" | "ready" | "error";
  version?: string;
  percent?: number;
  message?: string;
}

type CleanupFn = () => void;

interface ElectronAPI {
  onOpenSettings: (callback: () => void) => CleanupFn;
  onToggleCommandPalette: (callback: () => void) => CleanupFn;
  onToggleSidebar: (callback: () => void) => CleanupFn;
  onToggleTerminal: (callback: () => void) => CleanupFn;
  onUpdateStatus: (
    callback: (data: { status: string; version?: string; percent?: number; message?: string }) => void,
  ) => CleanupFn;
  selectProjectDirectory: () => Promise<string | null>;
  platform: string;
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}

interface UseElectronIPCHandlers {
  onOpenSettings: () => void;
  onToggleCommandPalette: () => void;
  onToggleSidebar: () => void;
  onToggleTerminal: () => void;
}

export function useElectronIPC(handlers: UseElectronIPCHandlers) {
  useEffect(() => {
    const api = window.electronAPI;
    if (!api) return;

    const cleanups = [
      api.onOpenSettings(handlers.onOpenSettings),
      api.onToggleCommandPalette(handlers.onToggleCommandPalette),
      api.onToggleSidebar(handlers.onToggleSidebar),
      api.onToggleTerminal(handlers.onToggleTerminal),
    ];
    return () => cleanups.forEach((fn) => fn());
  }, [handlers.onOpenSettings, handlers.onToggleCommandPalette, handlers.onToggleSidebar, handlers.onToggleTerminal]);
}

export function useUpdateStatus(): UpdateStatus {
  const [status, setStatus] = useState<UpdateStatus>({ status: "idle" });

  const handler = useCallback(
    (data: { status: string; version?: string; percent?: number; message?: string }) => {
      setStatus({
        status: data.status as UpdateStatus["status"],
        version: data.version,
        percent: data.percent,
        message: data.message,
      });
    },
    [],
  );

  useEffect(() => {
    const api = window.electronAPI;
    if (!api?.onUpdateStatus) return;
    const cleanup = api.onUpdateStatus(handler);
    return cleanup;
  }, [handler]);

  return status;
}
