import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Settings as SettingsIcon, PanelRightOpen } from "lucide-react";
import { Header } from "@/components/layout/Header";
import { Sidebar } from "@/components/layout/Sidebar";
import { ActivityFeed } from "@/components/chat/ActivityFeed";
import { ChatInput } from "@/components/chat/ChatInput";
import { ContextPanel } from "@/components/panels/ContextPanel";
import { SettingsModal } from "@/components/SettingsModal";
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
import { api } from "@/api/client";
import type { WorkspaceFile } from "@/api/types";

type BottomTab = "terminal" | "problems";

interface OpenFile {
  path: string;
  name: string;
  content: string;
  language: string;
  modified: boolean;
  originalContent: string;
}

function detectLanguage(path: string): string {
  if (path.endsWith(".yml") || path.endsWith(".yaml")) return "yaml";
  if (path.endsWith(".json")) return "json";
  return "plaintext";
}

export function App() {
  const { health, error: healthError, refresh: refreshHealth } = useHealth();
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
      activeSessionId: session.activeId,
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

  const ansibleCtx = useAnsibleContext(
    session.active.events,
    session.active.workspaceFiles
  );

  const handleSend = (message: string) => {
    chat.send(message, session.active.id);
  };

  const handleLLMUpdate = async (patch: Parameters<typeof llm.update>[0]) => {
    await llm.update(patch);
    refreshHealth();
  };

  const handleLLMReset = async () => {
    await llm.reset();
    refreshHealth();
  };

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

  const handleEditorSave = useCallback(
    async (value: string) => {
      if (!activeFilePath || !session.active.id) return;
      const sessionId = session.active.id;
      if (sessionId.startsWith("local-")) return;

      try {
        await api.saveFile(sessionId, activeFilePath, value);
        setOpenFiles((prev) =>
          prev.map((f) =>
            f.path === activeFilePath
              ? { ...f, modified: false, originalContent: value }
              : f
          )
        );
      } catch {
        // save failed
      }
    },
    [activeFilePath, session.active.id]
  );

  const handleOpenFileFromLint = useCallback(
    (path: string, _line: number) => {
      const wsFile = session.active.workspaceFiles.find(
        (f) => f.path === path || f.path.endsWith(path)
      );
      if (wsFile) openFileInEditor(wsFile);
    },
    [session.active.workspaceFiles, openFileInEditor]
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

  const isPendingApproval = session.active.status === "awaiting_approval";

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
            if (isPendingApproval) chat.approve(session.active.id);
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
      [activeFilePath, closeFile, isPendingApproval, chat, session.active.id]
    )
  );

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <Header
        health={health}
        llmSettings={llm.settings}
        onSettingsClick={() => {
          llm.refresh();
          setSettingsOpen(true);
        }}
        sessionTitle={session.active.title}
      />

      <div className="flex flex-1 overflow-hidden">
        {sidebarOpen && (
          <Sidebar
            sessions={session.sessions}
            activeId={session.activeId}
            onSelect={session.setActiveId}
            onNew={session.newSession}
            onDelete={session.deleteSession}
            onClearAll={session.clearAllSessions}
          />
        )}

        {/* Chat pane — fills remaining space */}
        <main className="flex flex-1 min-w-0 flex-col overflow-hidden">
          {healthError && (
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

          <ActivityFeed
            events={session.active.events}
            isStreaming={chat.isStreaming}
            isPendingApproval={isPendingApproval}
            onApprove={() => chat.approve(session.active.id)}
            onReject={() => chat.reject(session.active.id)}
            onQuickAction={(prompt) => setDraftPrompt(prompt)}
          />

          <div className="shrink-0 border-t border-zinc-800 bg-zinc-950 p-3">
            <div className="flex items-center gap-2">
              <div className="flex-1">
                <ChatInput
                  onSend={handleSend}
                  onCancel={chat.cancel}
                  isStreaming={chat.isStreaming}
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
                  title="Open context panel (⌘B)"
                >
                  <PanelRightOpen className="h-4 w-4" />
                </button>
              )}
            </div>
          </div>
        </main>

        {/* Right panel — editor / context */}
        {contextOpen && (
          <>
            {/* Drag handle */}
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
              {/* Top: editor or context */}
              <div
                className="flex-1 min-h-0 flex flex-col overflow-hidden"
              >
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
                    events={session.active.events}
                    isStreaming={chat.isStreaming}
                    onCollapse={() => setContextOpen(false)}
                    playbooks={session.active.playbooks}
                    inventory={session.active.inventory}
                    workspaceFiles={session.active.workspaceFiles}
                    onOpenFile={openFileInEditor}
                  />
                )}
              </div>

              {/* Bottom: terminal / problems */}
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
                            session.active.id.startsWith("local-")
                              ? null
                              : session.active.id
                          }
                          visible
                        />
                      )}
                      {bottomTab === "problems" && (
                        <LintPanel
                          sessionId={
                            session.active.id.startsWith("local-")
                              ? null
                              : session.active.id
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

      {/* Status bar */}
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
        workspaceFiles={session.active.workspaceFiles}
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
    </div>
  );
}
