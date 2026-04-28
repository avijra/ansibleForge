import { useState } from "react";
import { FileCode2, FolderTree, GitCompare, ScrollText } from "lucide-react";
import type { AgentEvent } from "@/api/types";
import { YamlEditor } from "./YamlEditor";
import { DiffViewer } from "./DiffViewer";
import { ExecutionLog } from "./ExecutionLog";
import { cn } from "@/lib/utils";

interface ArtifactPanelProps {
  playbooks: Record<string, string>;
  inventory: Record<string, string>;
  events: AgentEvent[];
}

type Tab = "playbooks" | "inventory" | "diff" | "logs";

const tabs: { id: Tab; label: string; icon: typeof FileCode2 }[] = [
  { id: "playbooks", label: "Playbooks", icon: FileCode2 },
  { id: "inventory", label: "Inventory", icon: FolderTree },
  { id: "diff", label: "Diff", icon: GitCompare },
  { id: "logs", label: "Logs", icon: ScrollText },
];

export function ArtifactPanel({ playbooks, inventory, events }: ArtifactPanelProps) {
  const [activeTab, setActiveTab] = useState<Tab>("playbooks");

  const pbEntries = Object.entries(playbooks);
  const invEntries = Object.entries(inventory);
  const hasContent = pbEntries.length > 0 || invEntries.length > 0 || events.length > 0;

  if (!hasContent) return null;

  return (
    <div className="shrink-0 border-t border-zinc-800 bg-zinc-950">
      <div className="flex items-center gap-0.5 border-b border-zinc-800 px-2">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              "flex items-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors border-b-2",
              activeTab === tab.id
                ? "border-blue-400 text-blue-400"
                : "border-transparent text-zinc-500 hover:text-zinc-300"
            )}
          >
            <tab.icon className="h-3.5 w-3.5" />
            {tab.label}
            {tab.id === "playbooks" && pbEntries.length > 0 && (
              <span className="ml-1 rounded bg-zinc-800 px-1 py-0.5 text-[10px] font-mono">
                {pbEntries.length}
              </span>
            )}
          </button>
        ))}
      </div>

      <div className="max-h-64 overflow-y-auto">
        {activeTab === "playbooks" && (
          <div className="p-2 space-y-2">
            {pbEntries.length === 0 ? (
              <EmptyState text="No playbooks generated yet" />
            ) : (
              pbEntries.map(([name, content]) => (
                <YamlEditor key={name} filename={name} content={content} />
              ))
            )}
          </div>
        )}

        {activeTab === "inventory" && (
          <div className="p-2 space-y-2">
            {invEntries.length === 0 ? (
              <EmptyState text="No inventory files" />
            ) : (
              invEntries.map(([name, content]) => (
                <YamlEditor key={name} filename={name} content={content} />
              ))
            )}
          </div>
        )}

        {activeTab === "diff" && <DiffViewer events={events} />}
        {activeTab === "logs" && <ExecutionLog events={events} />}
      </div>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <p className="py-6 text-center text-xs text-zinc-600">{text}</p>
  );
}
