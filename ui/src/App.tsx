import { useEffect, useRef, useState } from "react";
import { Settings as SettingsIcon, PanelRightOpen } from "lucide-react";
import { Panel, Group as PanelGroup, Separator as PanelResizeHandle } from "react-resizable-panels";
import { Header } from "@/components/layout/Header";
import { Sidebar } from "@/components/layout/Sidebar";
import { ActivityFeed } from "@/components/chat/ActivityFeed";
import { ChatInput } from "@/components/chat/ChatInput";
import { ContextPanel } from "@/components/panels/ContextPanel";
import { SettingsModal } from "@/components/SettingsModal";
import { useHealth } from "@/hooks/useHealth";
import { useSession } from "@/hooks/useSession";
import { useChat } from "@/hooks/useChat";
import { useLLMSettings } from "@/hooks/useLLMSettings";

export function App() {
  const { health, refresh: refreshHealth } = useHealth();
  const session = useSession();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [setupDismissed, setSetupDismissed] = useState(false);
  const [contextOpen, setContextOpen] = useState(true);
  const [draftPrompt, setDraftPrompt] = useState("");
  const llm = useLLMSettings();
  const autoOpenedRef = useRef(false);

  const needsSetup =
    llm.settings !== null && !llm.settings.api_key_set && llm.settings.source === "env";

  useEffect(() => {
    if (needsSetup && !autoOpenedRef.current) {
      autoOpenedRef.current = true;
      setSettingsOpen(true);
    }
  }, [needsSetup]);

  const chat = useChat({
    addEvent: session.addEvent,
    updateStatus: session.updateStatus,
    updateSessionId: session.updateSessionId,
    setPlaybooks: session.setPlaybooks,
    setInventory: session.setInventory,
  });

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

  const isPendingApproval = session.active.status === "awaiting_approval";

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
        <Sidebar
          sessions={session.sessions}
          activeId={session.activeId}
          onSelect={session.setActiveId}
          onNew={session.newSession}
          onDelete={session.deleteSession}
        />

        <PanelGroup orientation="horizontal" className="flex-1 min-w-0">
          {/* Center pane — chat */}
          <Panel defaultSize={contextOpen ? "55%" : "100%"} minSize="30%" className="min-w-0">
            <main className="flex h-full w-full min-w-0 flex-col overflow-hidden">
              {needsSetup && !setupDismissed && !settingsOpen && (
                <div className="mx-4 mt-3 flex items-center gap-3 rounded-lg border border-amber-700/50 bg-amber-950/30 px-4 py-3">
                  <SettingsIcon className="h-4 w-4 shrink-0 text-amber-400" />
                  <div className="flex-1 text-xs text-amber-200">
                    <span className="font-medium">Setup required</span> — Configure your model provider and API key to get started.
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
            </main>
          </Panel>

          {/* Resize handle */}
          {contextOpen && (
            <>
              <PanelResizeHandle className="w-1.5 bg-zinc-900 hover:bg-teal-500/30 active:bg-teal-500/50 transition-colors cursor-col-resize flex items-center justify-center group">
                <div className="h-8 w-0.5 rounded-full bg-zinc-700 group-hover:bg-teal-400/60 transition-colors" />
              </PanelResizeHandle>

              {/* Right panel — context */}
              <Panel defaultSize="45%" minSize="20%" maxSize="65%" className="min-w-0">
                <ContextPanel
                  events={session.active.events}
                  isStreaming={chat.isStreaming}
                  onCollapse={() => setContextOpen(false)}
                  playbooks={session.active.playbooks}
                  inventory={session.active.inventory}
                />
              </Panel>
            </>
          )}
        </PanelGroup>
      </div>

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
