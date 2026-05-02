/* eslint-disable @typescript-eslint/no-var-requires */
const { app, BrowserWindow, Menu, shell, dialog, ipcMain } = require("electron") as typeof import("electron");
import { spawn, type ChildProcess } from "child_process";
import * as fs from "fs";
import * as net from "net";
import * as path from "path";

let mainWindow: InstanceType<typeof BrowserWindow> | null = null;
let backendProcess: ChildProcess | null = null;
let creatingWindow = false;
const PORT = 8420;

function isPortAvailable(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.once("listening", () => {
      server.close();
      resolve(true);
    });
    server.listen(port);
  });
}

async function waitForBackend(maxRetries = 30): Promise<void> {
  const http = require("http") as typeof import("http");
  for (let i = 0; i < maxRetries; i++) {
    try {
      const ok = await new Promise<boolean>((resolve) => {
        const req = http.get(`http://127.0.0.1:${PORT}/api/v1/health`, (res) => {
          resolve(res.statusCode === 200);
          res.resume();
        });
        req.on("error", () => resolve(false));
        req.setTimeout(2000, () => { req.destroy(); resolve(false); });
      });
      if (ok) return;
    } catch {
      // not ready yet
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
}

function getBackendCommand(): { cmd: string; args: string[]; cwd: string } {
  if (app.isPackaged) {
    const backendDir = path.join(process.resourcesPath, "backend");
    const bin = process.platform === "win32"
      ? path.join(backendDir, "ansibleforge-backend.exe")
      : path.join(backendDir, "ansibleforge-backend");
    return { cmd: bin, args: [], cwd: backendDir };
  }

  const electronDir = path.resolve(__dirname, "..");
  const projectRoot = path.resolve(electronDir, "..");
  const venvPython = path.join(projectRoot, ".venv", "bin", "python");
  const pythonCmd = fs.existsSync(venvPython)
    ? venvPython
    : process.platform === "win32"
      ? "python"
      : "python3";
  return { cmd: pythonCmd, args: ["-m", "ansible_forge.main"], cwd: projectRoot };
}

function startBackend(): void {
  const { cmd, args, cwd } = getBackendCommand();

  backendProcess = spawn(cmd, args, {
    cwd,
    env: {
      ...process.env,
      ANSIBLEFORGE_HOST: "127.0.0.1",
      ANSIBLEFORGE_PORT: String(PORT),
      ANSIBLEFORGE_PARENT_PID: String(process.pid),
    },
    stdio: ["ignore", "pipe", "pipe"],
  });

  backendProcess.stdout?.on("data", (data: Buffer) => {
    process.stdout.write(`[backend] ${data}`);
  });

  backendProcess.stderr?.on("data", (data: Buffer) => {
    process.stderr.write(`[backend] ${data}`);
  });

  backendProcess.on("exit", (code) => {
    console.log(`Backend exited with code ${code}`);
    backendProcess = null;
  });
}

function stopBackend(): void {
  if (!backendProcess) return;
  const proc = backendProcess;
  backendProcess = null;

  proc.kill("SIGTERM");

  setTimeout(() => {
    try {
      if (!proc.killed) proc.kill("SIGKILL");
    } catch {
      // already dead
    }
  }, 3000);
}

function checkForUpdates(): void {
  if (!app.isPackaged) return;

  try {
    const { autoUpdater } = require("electron-updater");
    autoUpdater.autoDownload = false;
    autoUpdater.autoInstallOnAppQuit = true;

    autoUpdater.on("update-available", (info: { version: string }) => {
      dialog
        .showMessageBox({
          type: "info",
          title: "Update Available",
          message: `Tuyere v${info.version} is available.`,
          detail: "Would you like to download it now? It will install when you next quit the app.",
          buttons: ["Download", "Later"],
          defaultId: 0,
          cancelId: 1,
        })
        .then((result: { response: number }) => {
          if (result.response === 0) {
            autoUpdater.downloadUpdate();
          }
        });
    });

    autoUpdater.on("error", (err: Error) => {
      console.log(`Auto-update check failed: ${err.message}`);
    });

    autoUpdater.checkForUpdates();
  } catch (err) {
    console.log("electron-updater not available, skipping update check");
  }
}

function buildMenu(): Electron.Menu {
  const template: Electron.MenuItemConstructorOptions[] = [
    {
      label: "Tuyere",
      submenu: [
        { role: "about" },
        { type: "separator" },
        {
          label: "Settings",
          accelerator: "CmdOrCtrl+,",
          click: () => mainWindow?.webContents.send("open-settings"),
        },
        { type: "separator" },
        { role: "quit" },
      ],
    },
    {
      label: "Edit",
      submenu: [
        { role: "undo" },
        { role: "redo" },
        { type: "separator" },
        { role: "cut" },
        { role: "copy" },
        { role: "paste" },
        { role: "selectAll" },
      ],
    },
    {
      label: "View",
      submenu: [
        {
          label: "Command Palette",
          accelerator: "CmdOrCtrl+K",
          click: () => mainWindow?.webContents.send("toggle-command-palette"),
        },
        {
          label: "Toggle Sidebar",
          accelerator: "CmdOrCtrl+B",
          click: () => mainWindow?.webContents.send("toggle-sidebar"),
        },
        {
          label: "Toggle Terminal",
          accelerator: "CmdOrCtrl+`",
          click: () => mainWindow?.webContents.send("toggle-terminal"),
        },
        { type: "separator" },
        { role: "toggleDevTools" },
        { role: "togglefullscreen" },
        { type: "separator" },
        { role: "zoomIn" },
        { role: "zoomOut" },
        { role: "resetZoom" },
      ],
    },
    {
      label: "Help",
      submenu: [
        {
          label: "Documentation",
          click: () => shell.openExternal("https://github.com/ansibleforge/ansibleforge"),
        },
        {
          label: "Report Issue",
          click: () => shell.openExternal("https://github.com/ansibleforge/ansibleforge/issues"),
        },
      ],
    },
  ];

  return Menu.buildFromTemplate(template);
}

ipcMain.handle("select-project-directory", async () => {
  const result = await dialog.showOpenDialog({
    title: "Select Project Directory",
    properties: ["openDirectory", "createDirectory"],
    buttonLabel: "Select",
  });
  if (result.canceled || result.filePaths.length === 0) {
    return null;
  }
  return result.filePaths[0];
});

async function createWindow(): Promise<void> {
  if (mainWindow || creatingWindow) return;
  creatingWindow = true;

  const iconPath = app.isPackaged
    ? path.join(process.resourcesPath, "..", "Resources", "icon.icns")
    : path.join(__dirname, "..", "build", "icon.png");

  if (process.platform === "darwin" && app.dock) {
    try {
      const { nativeImage } = require("electron") as typeof import("electron");
      const rawIcon = nativeImage.createFromPath(
        path.join(__dirname, "..", "build", "icon.png")
      );
      if (!rawIcon.isEmpty()) {
        const dockIcon = rawIcon.resize({ width: 128, height: 128 });
        app.dock.setIcon(dockIcon);
      }
    } catch { /* icon not found in dev — acceptable */ }
  }

  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 960,
    minHeight: 600,
    title: "Tuyere",
    icon: iconPath,
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 12, y: 12 },
    backgroundColor: "#09090b",
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, "preload.js"),
    },
  });

  Menu.setApplicationMenu(buildMenu());

  mainWindow.loadURL(`http://127.0.0.1:${PORT}`);

  if (!app.isPackaged) {
    mainWindow.webContents.openDevTools({ mode: "bottom" });
  }

  mainWindow.on("closed", () => {
    mainWindow = null;
    creatingWindow = false;
  });

  creatingWindow = false;
}

const gotLock = app.requestSingleInstanceLock();

if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.setName("Tuyere");

  app.on("ready", async () => {
    const portFree = await isPortAvailable(PORT);
    if (portFree) {
      startBackend();
      await waitForBackend();
    }
    await createWindow();
    checkForUpdates();
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") {
      app.quit();
    }
  });

  app.on("activate", async () => {
    if (mainWindow) {
      mainWindow.focus();
    } else {
      await createWindow();
    }
  });

  app.on("before-quit", () => {
    stopBackend();
  });
}
