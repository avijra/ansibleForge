import { AlertTriangle } from "lucide-react";
import type { AgentEvent } from "@/api/types";

export function ErrorEvent({ event }: { event: AgentEvent }) {
  const error =
    (event.data.error as string) || (event.data.message as string) || "Unknown error";
  const tool = event.data.tool as string | undefined;

  return (
    <div className="animate-slide-in rounded-lg border border-red-800/30 bg-red-950/15 shadow-[0_0_12px_-4px_rgba(239,68,68,0.12)] p-3 space-y-1">
      <div className="flex items-center gap-2">
        <AlertTriangle className="h-3.5 w-3.5 text-zinc-400" />
        <span className="text-xs font-medium text-zinc-400">
          {tool ? `Error in ${tool}` : "Error"}
        </span>
      </div>
      <p className="text-xs text-zinc-400/80 font-mono whitespace-pre-wrap">
        {error}
      </p>
    </div>
  );
}
