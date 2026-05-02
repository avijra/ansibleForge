import { useState } from "react";
import { Wrench, ChevronDown, ChevronRight } from "lucide-react";
import type { AgentEvent } from "@/api/types";
import { JsonBlock } from "@/components/common/JsonBlock";
import { describeToolCall, friendlyToolName } from "@/lib/tool-labels";

export function ToolCallEvent({ event }: { event: AgentEvent }) {
  const tool = (event.data.tool as string) || "unknown";
  const args = event.data.arguments as Record<string, unknown> | undefined;
  const [detailsOpen, setDetailsOpen] = useState(false);
  const summary = describeToolCall(tool, args);
  const hasArgs = args && Object.keys(args).length > 0;

  return (
    <div className="animate-slide-in rounded-lg border border-blue-800/25 bg-blue-950/15 shadow-[0_0_12px_-4px_rgba(59,130,246,0.10)] p-3 space-y-1.5">
      <div className="flex items-center gap-2">
        <Wrench className="h-3.5 w-3.5 text-zinc-400" />
        <span className="text-xs font-medium text-zinc-300">{summary}</span>
      </div>
      {hasArgs && (
        <button
          onClick={() => setDetailsOpen(!detailsOpen)}
          className="flex items-center gap-1 text-[10px] text-zinc-600 hover:text-zinc-400 transition-colors"
        >
          {detailsOpen
            ? <ChevronDown className="h-3 w-3" />
            : <ChevronRight className="h-3 w-3" />
          }
          <span>Details</span>
        </button>
      )}
      {detailsOpen && hasArgs && <JsonBlock data={args} maxLines={8} />}
    </div>
  );
}
