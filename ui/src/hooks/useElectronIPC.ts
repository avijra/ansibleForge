import { useEffect } from "react";

interface ElectronAPI {
  onOpenSettings: (callback: () => void) => void;
  onToggleCommandPalette: (callback: () => void) => void;
  onToggleSidebar: (callback: () => void) => void;
  onToggleTerminal: (callback: () => void) => void;
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

    api.onOpenSettings(handlers.onOpenSettings);
    api.onToggleCommandPalette(handlers.onToggleCommandPalette);
    api.onToggleSidebar(handlers.onToggleSidebar);
    api.onToggleTerminal(handlers.onToggleTerminal);
  }, [handlers.onOpenSettings, handlers.onToggleCommandPalette, handlers.onToggleSidebar, handlers.onToggleTerminal]);
}
