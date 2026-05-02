import { useState } from "react";
import { ScrollText, Server, GitBranch, Brain, PanelRightClose, FolderTree, BookOpen } from "lucide-react";
import { cn } from "@/lib/utils";
import { ExecutionTimeline } from "./ExecutionTimeline";
import { HostInventory } from "./HostInventory";
import { RunHistory } from "./RunHistory";
import { KnowledgeExplorer } from "./KnowledgeExplorer";
import { WorkspaceExplorer } from "./WorkspaceExplorer";
import { RulesEditor } from "./RulesEditor";
import type { AgentEvent, WorkspaceFile } from "@/api/types";

export type ContextTab = "logs" | "files" | "hosts" | "runs" | "knowledge" | "rules";

const tabs: { id: ContextTab; label: string; icon: typeof ScrollText }[] = [
  { id: "logs", label: "Logs", icon: ScrollText },
  { id: "files", label: "Files", icon: FolderTree },
  { id: "hosts", label: "Hosts", icon: Server },
  { id: "runs", label: "Runs", icon: GitBranch },
  { id: "knowledge", label: "Knowledge", icon: Brain },
  { id: "rules", label: "Rules", icon: BookOpen },
];

interface ContextPanelProps {
  events: AgentEvent[];
  isStreaming: boolean;
  onCollapse: () => void;
  playbooks: Record<string, string>;
  inventory: Record<string, string>;
  workspaceFiles: WorkspaceFile[];
  onOpenFile?: (file: WorkspaceFile) => void;
  sessionId?: string;
}

export function ContextPanel({
  events,
  isStreaming,
  onCollapse,
  playbooks,
  inventory,
  workspaceFiles,
  onOpenFile,
  sessionId,
}: ContextPanelProps) {
  const [activeTab, setActiveTab] = useState<ContextTab>("logs");

  const fileCount = workspaceFiles.length;

  return (
    <div className="flex h-full w-full min-w-0 flex-col bg-zinc-950">
      <div className="flex shrink-0 items-center border-b border-zinc-800 min-w-0">
        <div className="flex flex-1 min-w-0 items-center gap-0.5 px-1 overflow-x-auto scrollbar-none" role="tablist">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              role="tab"
              aria-selected={activeTab === tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "flex items-center gap-1.5 px-2.5 py-2.5 text-xs font-medium transition-colors border-b-2 whitespace-nowrap shrink-0",
                activeTab === tab.id
                  ? "border-zinc-400 text-zinc-200"
                  : "border-transparent text-zinc-500 hover:text-zinc-300"
              )}
            >
              <tab.icon className="h-3.5 w-3.5" />
              {tab.label}
              {tab.id === "files" && fileCount > 0 && (
                <span className="ml-0.5 rounded bg-zinc-800 px-1 py-0.5 text-[10px] font-mono leading-none">
                  {fileCount}
                </span>
              )}
            </button>
          ))}
        </div>
        <button
          onClick={onCollapse}
          className="mr-2 rounded-md p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300 transition-colors shrink-0"
          aria-label="Collapse panel"
          title="Collapse panel"
        >
          <PanelRightClose className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="flex-1 min-w-0 overflow-hidden">
        {activeTab === "logs" && (
          <div className="h-full overflow-y-auto overflow-x-hidden">
            <ExecutionTimeline
              events={events}
              isStreaming={isStreaming}
              playbooks={playbooks}
              inventory={inventory}
            />
          </div>
        )}
        {activeTab === "files" && <WorkspaceExplorer files={workspaceFiles} onOpenFile={onOpenFile} />}
        {activeTab === "hosts" && (
          <div className="h-full overflow-y-auto overflow-x-hidden">
            <HostInventory events={events} />
          </div>
        )}
        {activeTab === "runs" && (
          <div className="h-full overflow-y-auto overflow-x-hidden">
            <RunHistory events={events} />
          </div>
        )}
        {activeTab === "knowledge" && (
          <div className="h-full overflow-y-auto overflow-x-hidden">
            <KnowledgeExplorer />
          </div>
        )}
        {activeTab === "rules" && (
          <div className="h-full overflow-y-auto overflow-x-hidden">
            <RulesEditor sessionId={sessionId} />
          </div>
        )}
      </div>
    </div>
  );
}
