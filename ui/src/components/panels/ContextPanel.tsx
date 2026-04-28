import { useState } from "react";
import { ScrollText, Server, GitBranch, Brain, PanelRightClose } from "lucide-react";
import { cn } from "@/lib/utils";
import { ExecutionTimeline } from "./ExecutionTimeline";
import { HostInventory } from "./HostInventory";
import { RunHistory } from "./RunHistory";
import { KnowledgeExplorer } from "./KnowledgeExplorer";
import type { AgentEvent } from "@/api/types";

export type ContextTab = "logs" | "hosts" | "runs" | "knowledge";

const tabs: { id: ContextTab; label: string; icon: typeof ScrollText }[] = [
  { id: "logs", label: "Logs", icon: ScrollText },
  { id: "hosts", label: "Hosts", icon: Server },
  { id: "runs", label: "Runs", icon: GitBranch },
  { id: "knowledge", label: "Knowledge", icon: Brain },
];

interface ContextPanelProps {
  events: AgentEvent[];
  isStreaming: boolean;
  onCollapse: () => void;
  playbooks: Record<string, string>;
  inventory: Record<string, string>;
}

export function ContextPanel({
  events,
  isStreaming,
  onCollapse,
  playbooks,
  inventory,
}: ContextPanelProps) {
  const [activeTab, setActiveTab] = useState<ContextTab>("logs");

  return (
    <div className="flex h-full w-full min-w-0 flex-col bg-zinc-950">
      <div className="flex shrink-0 items-center border-b border-zinc-800 min-w-0">
        <div className="flex flex-1 min-w-0 items-center gap-0.5 px-1">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-2.5 text-xs font-medium transition-colors border-b-2",
                activeTab === tab.id
                  ? "border-teal-400 text-teal-400"
                  : "border-transparent text-zinc-500 hover:text-zinc-300"
              )}
            >
              <tab.icon className="h-3.5 w-3.5" />
              {tab.label}
            </button>
          ))}
        </div>
        <button
          onClick={onCollapse}
          className="mr-2 rounded-md p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300 transition-colors"
          aria-label="Collapse panel"
          title="Collapse panel"
        >
          <PanelRightClose className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="flex-1 min-w-0 overflow-y-auto overflow-x-hidden">
        {activeTab === "logs" && (
          <ExecutionTimeline
            events={events}
            isStreaming={isStreaming}
            playbooks={playbooks}
            inventory={inventory}
          />
        )}
        {activeTab === "hosts" && <HostInventory events={events} />}
        {activeTab === "runs" && <RunHistory events={events} />}
        {activeTab === "knowledge" && <KnowledgeExplorer />}
      </div>
    </div>
  );
}
