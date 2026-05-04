const { contextBridge, ipcRenderer } = require("electron") as typeof import("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  onOpenSettings: (callback: () => void) => {
    ipcRenderer.on("open-settings", callback);
    return () => ipcRenderer.removeListener("open-settings", callback);
  },
  onToggleCommandPalette: (callback: () => void) => {
    ipcRenderer.on("toggle-command-palette", callback);
    return () => ipcRenderer.removeListener("toggle-command-palette", callback);
  },
  onToggleSidebar: (callback: () => void) => {
    ipcRenderer.on("toggle-sidebar", callback);
    return () => ipcRenderer.removeListener("toggle-sidebar", callback);
  },
  onToggleTerminal: (callback: () => void) => {
    ipcRenderer.on("toggle-terminal", callback);
    return () => ipcRenderer.removeListener("toggle-terminal", callback);
  },
  onUpdateStatus: (
    callback: (status: { status: string; version?: string; percent?: number; message?: string }) => void,
  ) => {
    const wrapped = (_event: unknown, data: Parameters<typeof callback>[0]) => callback(data);
    ipcRenderer.on("update-status", wrapped);
    return () => ipcRenderer.removeListener("update-status", wrapped);
  },
  selectProjectDirectory: (): Promise<string | null> =>
    ipcRenderer.invoke("select-project-directory"),
  platform: process.platform,
});
