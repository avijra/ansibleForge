import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Cpu, Settings as SettingsIcon, PanelRightOpen, FolderOpen } from "lucide-react";
import { Header } from "@/components/layout/Header";
import { Sidebar, type SidebarView } from "@/components/layout/Sidebar";
import { HostsView } from "@/components/views/HostsView";
import { RunsView } from "@/components/views/RunsView";
import { ActivityFeed } from "@/components/chat/ActivityFeed";
import { ChatInput } from "@/components/chat/ChatInput";
import { ContextPanel } from "@/components/panels/ContextPanel";
import { SettingsModal } from "@/components/SettingsModal";
import { ProjectSessionPicker } from "@/components/ProjectSessionPicker";
import { CodeEditor } from "@/components/editor/CodeEditor";
import { FileTabs } from "@/components/editor/FileTabs";
import { CommandPalette } from "@/components/command/CommandPalette";
import { TerminalPanel } from "@/components/terminal/Terminal";
import { LintPanel } from "@/components/panels/LintPanel";
import { useHealth } from "@/hooks/useHealth";
import { useSession } from "@/hooks/useSession";
import { useChat } from "@/hooks/useChat";
import { useLLMSettings } from "@/hooks/useLLMSettings";
import { useKeyboard } from "@/hooks/useKeyboard";
import { useAnsibleContext } from "@/hooks/useAnsibleContext";
import { useResizable } from "@/hooks/useResizable";
import { useTauriIPC, useUpdateStatus, pickDirectoryTauri } from "@/hooks/useTauriIPC";
import { api, request } from "@/api/client";
import type { AgentEvent, SessionListItem, WorkspaceFile } from "@/api/types";

type BottomTab = "terminal" | "problems";

interface OpenFile {
  path: string;
  name: string;
  content: string;
  language: string;
  modified: boolean;
  originalContent: string;
}

interface PickerState {
  projectPath: string;
  sessions: SessionListItem[];
}

function detectLanguage(path: string): string {
  if (path.endsWith(".yml") || path.endsWith(".yaml")) return "yaml";
  if (path.endsWith(".json")) return "json";
  return "plaintext";
}

async function pickDirectory(): Promise<string | null> {
  return pickDirectoryTauri();
}

export function App() {
  const { health, error: healthError, starting: backendStarting, refresh: refreshHealth } = useHealth();
  const session = useSession();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [setupDismissed, setSetupDismissed] = useState(false);
  const [contextOpen, setContextOpen] = useState(true);
  const [draftPrompt, setDraftPrompt] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const llm = useLLMSettings();
  const autoOpenedRef = useRef(false);

  const [openFiles, setOpenFiles] = useState<OpenFile[]>([]);
  const [activeFilePath, setActiveFilePath] = useState<string | null>(null);
  const [cmdPaletteOpen, setCmdPaletteOpen] = useState(false);
  const [bottomTab, setBottomTab] = useState<BottomTab | null>(null);
  const [activeView, setActiveView] = useState<SidebarView>("chat");
  const [pickerState, setPickerState] = useState<PickerState | null>(null);

  const rightPanel = useResizable({
    direction: "horizontal",
    initialSize: 520,
    minSize: 250,
    maxSize: 900,
  });

  const bottomPanel = useResizable({
    direction: "vertical",
    initialSize: 220,
    minSize: 100,
    maxSize: 500,
  });

  const activeFile = openFiles.find((f) => f.path === activeFilePath) ?? null;

  const needsSetup =
    llm.settings !== null && !llm.settings.api_key_set && llm.settings.source === "env";

  useEffect(() => {
    if (needsSetup && !autoOpenedRef.current) {
      autoOpenedRef.current = true;
      setSettingsOpen(true);
    }
  }, [needsSetup]);

  const chatOpts = useMemo(
    () => ({
      addEvent: session.addEvent,
      updateStatus: session.updateStatus,
      updateSessionId: session.updateSessionId,
      setPlaybooks: session.setPlaybooks,
      setInventory: session.setInventory,
      setWorkspaceFiles: session.setWorkspaceFiles,
      activeSessionId: session.activeId ?? undefined,
    }),
    [
      session.addEvent,
      session.updateStatus,
      session.updateSessionId,
      session.setPlaybooks,
      session.setInventory,
      session.setWorkspaceFiles,
      session.activeId,
    ]
  );
  const chat = useChat(chatOpts);

  useEffect(() => {
    const sid = session.active?.id;
    if (!sid || sid.startsWith("local-")) return;
    let cancelled = false;

    api.workspaceFiles(sid)
      .then((ws) => {
        if (!cancelled) session.setWorkspaceFiles(sid, ws.files);
      })
      .catch((err) => { console.warn("[workspace-files] fetch failed for", sid, err); });

    const toolEvents = session.active?.events.filter(
      (e) => e.event === "tool_result" || e.event === "tool_call"
    ) ?? [];
    if (toolEvents.length === 0) {
      request<{ events: Array<{ event_type: string; data: Record<string, unknown>; timestamp: number }> }>(
        `/sessions/${sid}/events`
      )
        .then((res) => {
          if (cancelled) return;
          if (!res.events || res.events.length === 0) return;
          const TRANSIENT = new Set(["progress", "thinking_delta", "message_delta"]);
          const mapped: AgentEvent[] = res.events
            .filter((e) => e.event_type && !TRANSIENT.has(e.event_type))
            .map((e, i) => ({
              id: `restored-${i}`,
              event: e.event_type as AgentEvent["event"],
              data: e.data,
              timestamp: e.timestamp * 1000,
            }));
          if (mapped.length > (session.active?.events.length ?? 0)) {
            session.setEvents(sid, mapped);
          }
        })
        .catch(() => {});
    }

    return () => { cancelled = true; };
  }, [session.active?.id]);

  const FILE_MUTATING_TOOLS = useMemo(() => new Set([
    "write_file", "generate_playbook", "scaffold_role", "manage_inventory",
    "render_template", "generate_terraform", "generate_rollback",
    "manage_vault", "import_project", "manage_git",
    "terraform_exec", "execute_playbook", "run_adhoc", "local_exec",
    "discover_inventory", "terraform_to_inventory", "run_molecule",
  ]), []);

  const wsRefreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastWsRefreshCount = useRef(0);

  const prevSessionIdRef = useRef<string | null>(null);

  useEffect(() => {
    const sid = session.active?.id;
    if (!sid || sid.startsWith("local-")) return;

    if (prevSessionIdRef.current !== sid) {
      lastWsRefreshCount.current = 0;
      prevSessionIdRef.current = sid;
    }

    const events = session.active?.events ?? [];
    const fileToolResults = events.filter(
      (e) => e.event === "tool_result" && FILE_MUTATING_TOOLS.has(e.data.tool as string)
    );
    if (fileToolResults.length === lastWsRefreshCount.current) return;
    lastWsRefreshCount.current = fileToolResults.length;

    if (wsRefreshTimer.current) clearTimeout(wsRefreshTimer.current);
    wsRefreshTimer.current = setTimeout(() => {
      api.workspaceFiles(sid)
        .then((ws) => session.setWorkspaceFiles(sid, ws.files))
        .catch(() => {});
    }, 600);
  }, [session.active?.id, session.active?.events, FILE_MUTATING_TOOLS]);

  const ansibleCtx = useAnsibleContext(
    session.active?.events ?? [],
    session.active?.workspaceFiles ?? []
  );

  const handleSend = (message: string) => {
    if (!session.active) return;
    chat.send(message, session.active.id, session.active.projectPath);
  };

  const handleLLMUpdate = async (patch: Parameters<typeof llm.update>[0]) => {
    await llm.update(patch);
    refreshHealth();
  };

  const handleLLMReset = async () => {
    await llm.reset();
    refreshHealth();
  };

  const handleOpenFolder = useCallback(async () => {
    const dir = await pickDirectory();
    if (!dir) return;

    const localMatches = session.sessions.filter((s) => s.projectPath === dir);

    let serverSessions: SessionListItem[] = [];
    try {
      const res = await api.sessions.list(dir);
      serverSessions = res.sessions;
    } catch {
      // backend may be down; fall through to local-only logic
    }

    const allIds = new Set([
      ...localMatches.map((s) => s.id),
      ...serverSessions.map((s) => s.session_id),
    ]);

    if (allIds.size === 0) {
      session.newSession(dir);
      setActiveView("chat");
      return;
    }

    if (allIds.size === 1 && localMatches.length === 1) {
      session.setActiveId(localMatches[0].id);
      setActiveView("chat");
      return;
    }

    const pickerSessions: SessionListItem[] = serverSessions.length > 0
      ? serverSessions
      : localMatches.map((s) => ({
          session_id: s.id,
          title: s.title ?? null,
          status: s.status,
          created_at: s.createdAt / 1000,
          updated_at: s.createdAt / 1000,
          project_path: s.projectPath ?? null,
        }));

    setPickerState({ projectPath: dir, sessions: pickerSessions });
  }, [session]);

  const handlePickerResume = useCallback(
    (sessionId: string) => {
      if (!pickerState) return;
      const existing = session.sessions.find((s) => s.id === sessionId);
      if (existing) {
        session.setActiveId(sessionId);
      } else {
        const serverEntry = pickerState.sessions.find((s) => s.session_id === sessionId);
        session.restoreRemoteSession(
          sessionId,
          pickerState.projectPath,
          serverEntry?.title ?? undefined
        );
      }
      setPickerState(null);
      setActiveView("chat");
    },
    [pickerState, session]
  );

  const handlePickerNew = useCallback(() => {
    if (!pickerState) return;
    session.newSession(pickerState.projectPath);
    setPickerState(null);
    setActiveView("chat");
  }, [pickerState, session]);

  const handleResetSession = useCallback(
    async (sessionId: string) => {
      await session.resetSession(sessionId);
    },
    [session]
  );

  const openFileInEditor = useCallback((file: WorkspaceFile) => {
    setOpenFiles((prev) => {
      const existing = prev.find((f) => f.path === file.path);
      if (existing) return prev;
      return [
        ...prev,
        {
          path: file.path,
          name: file.name,
          content: file.content,
          language: detectLanguage(file.path),
          modified: false,
          originalContent: file.content,
        },
      ];
    });
    setActiveFilePath(file.path);
  }, []);

  const closeFile = useCallback(
    (path: string) => {
      setOpenFiles((prev) => {
        const filtered = prev.filter((f) => f.path !== path);
        if (activeFilePath === path) {
          setActiveFilePath(filtered.length > 0 ? filtered[filtered.length - 1].path : null);
        }
        return filtered;
      });
    },
    [activeFilePath]
  );

  const handleEditorChange = useCallback(
    (value: string) => {
      if (!activeFilePath) return;
      setOpenFiles((prev) =>
        prev.map((f) =>
          f.path === activeFilePath
            ? { ...f, content: value, modified: value !== f.originalContent }
            : f
        )
      );
    },
    [activeFilePath]
  );

  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (!saveError) return;
    const t = setTimeout(() => setSaveError(null), 4000);
    return () => clearTimeout(t);
  }, [saveError]);

  const handleEditorSave = useCallback(
    async (value: string) => {
      if (!activeFilePath || !session.active?.id) return;
      const sessionId = session.active.id;
      if (sessionId.startsWith("local-")) {
        setSaveError("Send a message first to create a workspace before saving.");
        return;
      }

      try {
        await api.saveFile(sessionId, activeFilePath, value);
        setOpenFiles((prev) =>
          prev.map((f) =>
            f.path === activeFilePath
              ? { ...f, modified: false, originalContent: value }
              : f
          )
        );
        setSaveError(null);
      } catch (err) {
        setSaveError(err instanceof Error ? err.message : "Failed to save file.");
      }
    },
    [activeFilePath, session.active?.id]
  );

  const handleOpenFileFromLint = useCallback(
    (path: string, _line: number) => {
      const wsFile = (session.active?.workspaceFiles ?? []).find(
        (f) => f.path === path || f.path.endsWith(path)
      );
      if (wsFile) openFileInEditor(wsFile);
    },
    [session.active?.workspaceFiles, openFileInEditor]
  );

  const handleCommandAction = useCallback(
    (action: string) => {
      switch (action) {
        case "nav-terminal":
          setBottomTab((prev) => (prev === "terminal" ? null : "terminal"));
          break;
        case "nav-sidebar":
          setSidebarOpen((prev) => !prev);
          break;
        case "settings-llm":
        case "settings-model":
          llm.refresh();
          setSettingsOpen(true);
          break;
        case "lint-file":
          setBottomTab("problems");
          break;
        default:
          break;
      }
    },
    [llm]
  );

  const isPendingApproval = session.active?.status === "awaiting_approval";
  const activeSessionId = session.active?.id ?? null;

  useKeyboard(
    useMemo(
      () => ({
        "meta+k": {
          handler: () => setCmdPaletteOpen(true),
          description: "Command Palette",
        },
        "meta+b": {
          handler: () => setSidebarOpen((p) => !p),
          description: "Toggle Sidebar",
        },
        "meta+`": {
          handler: () =>
            setBottomTab((p) => (p === "terminal" ? null : "terminal")),
          description: "Toggle Terminal",
        },
        "meta+shift+m": {
          handler: () =>
            setBottomTab((p) => (p === "problems" ? null : "problems")),
          description: "Toggle Problems",
        },
        "meta+j": {
          handler: () => setBottomTab((p) => (p ? null : "terminal")),
          description: "Toggle Bottom Panel",
        },
        "meta+shift+a": {
          handler: () => {
            if (isPendingApproval && activeSessionId) chat.approve(activeSessionId);
          },
          description: "Approve Execution",
        },
        "meta+w": {
          handler: () => {
            if (activeFilePath) closeFile(activeFilePath);
          },
          description: "Close File",
        },
        escape: {
          handler: () => setCmdPaletteOpen(false),
          description: "Close Palette",
        },
      }),
      [activeFilePath, closeFile, isPendingApproval, chat, activeSessionId]
    )
  );

  useTauriIPC(
    useMemo(
      () => ({
        onOpenSettings: () => { llm.refresh(); setSettingsOpen(true); },
        onToggleCommandPalette: () => setCmdPaletteOpen((p) => !p),
        onToggleSidebar: () => setSidebarOpen((p) => !p),
        onToggleTerminal: () => setBottomTab((p) => (p === "terminal" ? null : "terminal")),
      }),
      [llm]
    )
  );

  const hasActiveSession = session.active != null;
  const updateStatus = useUpdateStatus();

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      {updateStatus.status === "downloading" && (
        <div className="shrink-0 bg-blue-900/80 px-3 py-1 text-center text-xs text-blue-200 font-mono">
          Downloading update{updateStatus.version ? ` v${updateStatus.version}` : ""}
          {updateStatus.percent != null && ` — ${updateStatus.percent}%`}
          ...
        </div>
      )}
      {updateStatus.status === "ready" && (
        <div className="shrink-0 bg-emerald-900/80 px-3 py-1 text-center text-xs text-emerald-200 font-mono">
          Update v{updateStatus.version} ready — restart Tuyere to apply
        </div>
      )}
      {updateStatus.status === "error" && (
        <div className="shrink-0 bg-red-900/60 px-3 py-1 text-center text-xs text-red-300 font-mono">
          Update failed{updateStatus.message ? `: ${updateStatus.message}` : ""}
        </div>
      )}
      <Header
        health={health}
        llmSettings={llm.settings}
        onSettingsClick={() => {
          llm.refresh();
          setSettingsOpen(true);
        }}
        sessionTitle={session.active?.title}
      />

      <div className="flex flex-1 overflow-hidden">
        {sidebarOpen && (
          <Sidebar
            sessions={session.sessions}
            activeId={session.activeId}
            activeView={activeView}
            onSelect={(id) => { session.setActiveId(id); setActiveView("chat"); }}
            onOpenFolder={handleOpenFolder}
            onDelete={(id) => { chat.cleanupSession(id); session.deleteSession(id); }}
            onReset={handleResetSession}
            onClearAll={() => { session.sessions.forEach((s) => chat.cleanupSession(s.id)); session.clearAllSessions(); }}
            onViewChange={setActiveView}
          />
        )}

        <main className="flex flex-1 min-w-0 flex-col overflow-hidden">
          {healthError && !backendStarting && (
            <div className="mx-4 mt-3 flex items-center gap-3 rounded-lg border border-red-700/50 bg-red-950/30 px-4 py-2">
              <span className="text-xs text-red-300">
                <span className="font-medium">Backend unreachable</span> —{" "}
                {healthError}
              </span>
              <button
                onClick={refreshHealth}
                className="ml-auto rounded-md bg-red-800/60 px-3 py-1 text-xs font-medium text-red-200 hover:bg-red-700/60 transition-colors"
              >
                Retry
              </button>
            </div>
          )}
          {backendStarting && (
            <div className="mx-4 mt-3 flex items-center gap-2 rounded-lg border border-zinc-700/50 bg-zinc-900/50 px-4 py-2">
              <div className="h-2 w-2 animate-pulse rounded-full bg-amber-400" />
              <span className="text-xs text-zinc-400">
                Starting backend...
              </span>
            </div>
          )}

          {needsSetup && !setupDismissed && !settingsOpen && (
            <div className="mx-4 mt-3 flex items-center gap-3 rounded-lg border border-amber-700/50 bg-amber-950/30 px-4 py-3">
              <SettingsIcon className="h-4 w-4 shrink-0 text-amber-400" />
              <div className="flex-1 text-xs text-amber-200">
                <span className="font-medium">Setup required</span> — Configure
                your model provider and API key to get started.
              </div>
              <button
                onClick={() => {
                  llm.refresh();
                  setSettingsOpen(true);
                }}
                className="rounded-md bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-500 transition-colors"
              >
                Configure
              </button>
              <button
                onClick={() => setSetupDismissed(true)}
                className="text-amber-500/60 hover:text-amber-400 transition-colors text-xs"
              >
                Dismiss
              </button>
            </div>
          )}

          {!hasActiveSession ? (
            <WelcomeScreen onOpenFolder={handleOpenFolder} />
          ) : activeView === "hosts" ? (
            <HostsView />
          ) : activeView === "runs" ? (
            <RunsView />
          ) : (
            <>
              <ActivityFeed
                events={session.active!.events}
                isStreaming={chat.isStreaming}
                sessionStatus={session.active!.status}
                isPendingApproval={isPendingApproval ?? false}
                onApprove={(data) => chat.approve(session.active!.id, data)}
                onReject={() => chat.reject(session.active!.id)}
                onQuickAction={(prompt) => setDraftPrompt(prompt)}
                onCancelSecret={async () => {
                  const sid = session.active?.id;
                  if (!sid) return;
                  try {
                    await api.secrets.cancel(sid);
                    session.updateStatus(sid, "active");
                  } catch {
                    session.addEvent(sid, {
                      id: `err-${Date.now()}`,
                      event: "error_recovery",
                      data: { error: "Failed to cancel secret request. Try sending a new message." },
                      timestamp: Date.now(),
                    });
                    session.updateStatus(sid, "error");
                  }
                }}
              />

              <SessionFooter
                events={session.active!.events}
                model={llm.settings?.model || ""}
              />

              <div className="shrink-0 border-t border-zinc-800 bg-zinc-950 p-3">
                <div className="flex items-center gap-2">
                  <div className="flex-1">
                    <ChatInput
                      onSend={handleSend}
                      onCancel={chat.cancel}
                      isStreaming={chat.isStreaming}
                      canCancel={session.active?.status === "active" || session.active?.status === "awaiting_approval" || session.active?.status === "awaiting_secret"}
                      draft={draftPrompt}
                      onDraftConsumed={() => setDraftPrompt("")}
                      suggestions={ansibleCtx.suggestions}
                      getFiltered={ansibleCtx.getFiltered}
                    />
                  </div>
                  {!contextOpen && (
                    <button
                      onClick={() => setContextOpen(true)}
                      className="rounded-md p-2 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300 transition-colors shrink-0"
                      aria-label="Open context panel"
                      title="Open context panel"
                    >
                      <PanelRightOpen className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </div>
            </>
          )}
        </main>

        {contextOpen && hasActiveSession && (
          <>
            <div
              onMouseDown={rightPanel.onMouseDown}
              className="w-2 shrink-0 bg-zinc-900 hover:bg-blue-500/30 active:bg-blue-500/40 transition-colors cursor-col-resize flex items-center justify-center group"
            >
              <div className="h-12 w-0.5 rounded-full bg-zinc-700 group-hover:bg-blue-400 transition-colors" />
            </div>

            <div
              className="shrink-0 flex flex-col overflow-hidden bg-zinc-950 border-l border-zinc-800"
              style={{ width: rightPanel.size }}
            >
              <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
                {activeFile ? (
                  <>
                    <FileTabs
                      openFiles={openFiles.map((f) => ({
                        path: f.path,
                        name: f.name,
                        modified: f.modified,
                      }))}
                      activeFile={activeFilePath}
                      onSelect={setActiveFilePath}
                      onClose={closeFile}
                    />
                    <div className="flex-1 min-h-0 overflow-hidden">
                      <CodeEditor
                        content={activeFile.content}
                        language={activeFile.language}
                        onChange={handleEditorChange}
                        onSave={handleEditorSave}
                      />
                    </div>
                  </>
                ) : (
                  <ContextPanel
                    events={session.active!.events}
                    isStreaming={chat.isStreaming}
                    onCollapse={() => setContextOpen(false)}
                    playbooks={session.active!.playbooks}
                    inventory={session.active!.inventory}
                    workspaceFiles={session.active!.workspaceFiles}
                    onOpenFile={openFileInEditor}
                    onRefreshFiles={() => {
                      const sid = session.active?.id;
                      if (sid && !sid.startsWith("local-")) {
                        api.workspaceFiles(sid)
                          .then((ws) => session.setWorkspaceFiles(sid, ws.files))
                          .catch(() => {});
                      }
                    }}
                    sessionId={session.activeId ?? undefined}
                  />
                )}
              </div>

              {bottomTab && (
                <>
                  <div
                    onMouseDown={bottomPanel.onMouseDown}
                    className="h-2 shrink-0 bg-zinc-900 hover:bg-blue-500/30 active:bg-blue-500/40 transition-colors cursor-row-resize flex items-center justify-center group"
                  >
                    <div className="w-12 h-0.5 rounded-full bg-zinc-700 group-hover:bg-blue-400 transition-colors" />
                  </div>

                  <div
                    className="shrink-0 flex flex-col overflow-hidden border-t border-zinc-800"
                    style={{ height: bottomPanel.size }}
                  >
                    <div className="flex items-center gap-1 px-2 py-1 border-b border-zinc-800/50 shrink-0">
                      <button
                        onClick={() => setBottomTab("terminal")}
                        className={`px-2 py-1 text-[11px] rounded transition-colors ${
                          bottomTab === "terminal"
                            ? "text-zinc-200 bg-zinc-800"
                            : "text-zinc-500 hover:text-zinc-300"
                        }`}
                      >
                        Terminal
                      </button>
                      <button
                        onClick={() => setBottomTab("problems")}
                        className={`px-2 py-1 text-[11px] rounded transition-colors ${
                          bottomTab === "problems"
                            ? "text-zinc-200 bg-zinc-800"
                            : "text-zinc-500 hover:text-zinc-300"
                        }`}
                      >
                        Problems
                      </button>
                      <div className="flex-1" />
                      <button
                        onClick={() => setBottomTab(null)}
                        className="text-zinc-600 hover:text-zinc-300 px-1 text-xs"
                      >
                        ✕
                      </button>
                    </div>
                    <div className="flex-1 min-h-0 overflow-hidden">
                      {bottomTab === "terminal" && (
                        <TerminalPanel
                          sessionId={
                            session.active!.id.startsWith("local-")
                              ? null
                              : session.active!.id
                          }
                          visible
                        />
                      )}
                      {bottomTab === "problems" && (
                        <LintPanel
                          sessionId={
                            session.active!.id.startsWith("local-")
                              ? null
                              : session.active!.id
                          }
                          onOpenFile={handleOpenFileFromLint}
                        />
                      )}
                    </div>
                  </div>
                </>
              )}
            </div>
          </>
        )}
      </div>

      {saveError && (
        <div className="mx-4 mb-1 flex items-center gap-2 rounded-lg border border-amber-700/50 bg-amber-950/30 px-4 py-2 text-xs text-amber-200">
          <span>{saveError}</span>
          <button onClick={() => setSaveError(null)} className="ml-auto text-amber-500/60 hover:text-amber-400 text-xs">Dismiss</button>
        </div>
      )}

      <div className="flex items-center justify-between border-t border-zinc-800 bg-zinc-900/50 px-3 py-0.5 text-[10px] text-zinc-600">
        <div className="flex items-center gap-3">
          <button
            onClick={() =>
              setBottomTab((p) => (p === "terminal" ? null : "terminal"))
            }
            className="hover:text-zinc-300 transition-colors"
          >
            Terminal
          </button>
          <button
            onClick={() =>
              setBottomTab((p) => (p === "problems" ? null : "problems"))
            }
            className="hover:text-zinc-300 transition-colors"
          >
            Problems
          </button>
        </div>
        <div className="flex items-center gap-3">
          {activeFile && (
            <>
              <span>{activeFile.language}</span>
              <span>{activeFile.modified ? "Modified" : "Saved"}</span>
            </>
          )}
          <button
            onClick={() => setCmdPaletteOpen(true)}
            className="hover:text-zinc-300 transition-colors"
          >
            ⌘K
          </button>
        </div>
      </div>

      <CommandPalette
        open={cmdPaletteOpen}
        onOpenChange={setCmdPaletteOpen}
        workspaceFiles={session.active?.workspaceFiles ?? []}
        onOpenFile={(file) => openFileInEditor(file)}
        onAction={handleCommandAction}
      />

      {settingsOpen && (
        <SettingsModal
          health={health}
          llmSettings={llm.settings}
          llmLoading={llm.loading}
          llmError={llm.error}
          onLLMUpdate={handleLLMUpdate}
          onLLMReset={handleLLMReset}
          onClose={() => setSettingsOpen(false)}
        />
      )}

      {pickerState && (
        <ProjectSessionPicker
          projectPath={pickerState.projectPath}
          sessions={pickerState.sessions}
          onResume={handlePickerResume}
          onNew={handlePickerNew}
          onClose={() => setPickerState(null)}
        />
      )}
    </div>
  );
}

function WelcomeScreen({ onOpenFolder }: { onOpenFolder: () => void }) {
  return (
    <div className="flex flex-1 items-center justify-center">
      <div className="text-center max-w-sm">
        <svg width="64" height="64" viewBox="0 0 120 120" fill="none" className="mx-auto mb-6 opacity-80">
          <path d="M20 52 L42 46 L42 74 L20 68 Z" fill="#9CA3AF" opacity="0.85"/>
          <path d="M42 44 L72 38 L72 82 L42 76 Z" fill="#9CA3AF"/>
          <path d="M72 50 Q85 48 98 44" stroke="#10B981" strokeWidth="3" strokeLinecap="round" opacity="0.8"/>
          <path d="M72 60 Q90 60 108 60" stroke="#10B981" strokeWidth="3" strokeLinecap="round" opacity="0.9"/>
          <path d="M72 70 Q85 72 98 76" stroke="#10B981" strokeWidth="3" strokeLinecap="round" opacity="0.8"/>
          <circle cx="108" cy="60" r="4" fill="#10B981" opacity="0.85"/>
        </svg>
        <h2 className="text-lg font-semibold text-zinc-100 mb-2">Welcome to Tuyere</h2>
        <p className="text-sm text-zinc-500 mb-6">
          Open a project folder to start an infrastructure automation session.
        </p>
        <button
          onClick={onOpenFolder}
          className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-emerald-500 transition-colors shadow-lg shadow-emerald-900/30"
        >
          <FolderOpen className="h-4 w-4" />
          Open Project Folder
        </button>
      </div>
    </div>
  );
}

function SessionFooter({ events, model }: { events: AgentEvent[]; model: string }) {
  const usage = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i--) {
      if (events[i].event === "usage") return events[i].data;
    }
    return null;
  }, [events]);

  const modelShort = model ? model.split("/").pop() || model : null;

  if (!modelShort && !usage) return null;

  const tokens = usage ? ((usage.total_tokens as number) || 0) : 0;
  const cost = usage ? ((usage.estimated_cost as number) || 0) : 0;
  const tokenFmt = tokens >= 1000 ? `${(tokens / 1000).toFixed(1)}k` : String(tokens);
  const costFmt = cost > 0 ? (cost < 0.01 ? `$${cost.toFixed(4)}` : `$${cost.toFixed(2)}`) : null;

  return (
    <div className="shrink-0 flex items-center gap-3 px-4 py-1 border-t border-zinc-800/30 bg-zinc-950/80 text-[10px] text-zinc-600">
      {modelShort && (
        <span className="flex items-center gap-1">
          <Cpu className="h-2.5 w-2.5" />
          {modelShort}
        </span>
      )}
      <span className="flex-1" />
      {usage && <span>{tokenFmt} tokens</span>}
      {costFmt && <span>{costFmt}</span>}
    </div>
  );
}
