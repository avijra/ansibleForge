import { useCallback, useEffect, useState } from "react";

export interface UpdateStatus {
  status: "idle" | "available" | "downloading" | "ready" | "error";
  version?: string;
  percent?: number;
  message?: string;
}

type CleanupFn = () => void;

interface UseTauriIPCHandlers {
  onOpenSettings: () => void;
  onToggleCommandPalette: () => void;
  onToggleSidebar: () => void;
  onToggleTerminal: () => void;
}

function isTauri(): boolean {
  return "__TAURI_INTERNALS__" in window;
}

export function useTauriIPC(handlers: UseTauriIPCHandlers) {
  useEffect(() => {
    if (!isTauri()) return;

    let cleanups: CleanupFn[] = [];
    let mounted = true;

    (async () => {
      const { listen } = await import("@tauri-apps/api/event");

      if (!mounted) return;

      const unlisten1 = await listen("open-settings", handlers.onOpenSettings);
      const unlisten2 = await listen(
        "toggle-command-palette",
        handlers.onToggleCommandPalette
      );
      const unlisten3 = await listen(
        "toggle-sidebar",
        handlers.onToggleSidebar
      );
      const unlisten4 = await listen(
        "toggle-terminal",
        handlers.onToggleTerminal
      );

      cleanups = [unlisten1, unlisten2, unlisten3, unlisten4];
    })();

    return () => {
      mounted = false;
      cleanups.forEach((fn) => fn());
    };
  }, [
    handlers.onOpenSettings,
    handlers.onToggleCommandPalette,
    handlers.onToggleSidebar,
    handlers.onToggleTerminal,
  ]);
}

export function useUpdateStatus(): UpdateStatus {
  const [status, setStatus] = useState<UpdateStatus>({ status: "idle" });

  const handler = useCallback(
    (data: {
      status: string;
      version?: string;
      percent?: number;
      message?: string;
    }) => {
      setStatus({
        status: data.status as UpdateStatus["status"],
        version: data.version,
        percent: data.percent,
        message: data.message,
      });
    },
    []
  );

  useEffect(() => {
    if (!isTauri()) return;

    let cleanup: CleanupFn | undefined;
    let mounted = true;

    (async () => {
      const { listen } = await import("@tauri-apps/api/event");
      if (!mounted) return;

      cleanup = await listen<{
        status: string;
        version?: string;
        percent?: number;
        message?: string;
      }>("update-status", (event) => {
        handler(event.payload);
      });
    })();

    return () => {
      mounted = false;
      cleanup?.();
    };
  }, [handler]);

  return status;
}

export async function pickDirectoryTauri(): Promise<string | null> {
  if (!isTauri()) {
    return prompt("Enter project directory path:");
  }

  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<string | null>("select_project_directory");
}

export async function sendNotification(
  title: string,
  body: string
): Promise<void> {
  if (!isTauri()) return;

  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("send_notification", { title, body });
  } catch {
    // Notification permission may not be granted
  }
}
