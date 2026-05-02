const { contextBridge, ipcRenderer } = require("electron") as typeof import("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  onOpenSettings: (callback: () => void) =>
    ipcRenderer.on("open-settings", callback),
  onToggleCommandPalette: (callback: () => void) =>
    ipcRenderer.on("toggle-command-palette", callback),
  onToggleSidebar: (callback: () => void) =>
    ipcRenderer.on("toggle-sidebar", callback),
  onToggleTerminal: (callback: () => void) =>
    ipcRenderer.on("toggle-terminal", callback),
  selectProjectDirectory: (): Promise<string | null> =>
    ipcRenderer.invoke("select-project-directory"),
  platform: process.platform,
});
