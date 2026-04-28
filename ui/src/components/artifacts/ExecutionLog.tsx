import type { AgentEvent } from "@/api/types";
import { cn } from "@/lib/utils";
import { formatTimestamp } from "@/lib/utils";

interface ExecutionLogProps {
  events: AgentEvent[];
}

export function ExecutionLog({ events }: ExecutionLogProps) {
  const logEvents = events.filter(
    (e) =>
      e.event === "tool_call" ||
      e.event === "tool_result" ||
      e.event === "step_start"
  );

  if (logEvents.length === 0) {
    return (
      <p className="py-6 text-center text-xs text-zinc-600">
        No execution logs yet.
      </p>
    );
  }

  return (
    <div className="p-2">
      <div className="rounded-md border border-zinc-800 bg-zinc-950 p-2 font-mono text-xs leading-relaxed max-h-60 overflow-y-auto">
        {logEvents.map((evt) => (
          <div key={evt.id} className="flex gap-2">
            <span className="shrink-0 text-zinc-700 w-18">
              {formatTimestamp(evt.timestamp)}
            </span>
            <span
              className={cn(
                "shrink-0 w-16",
                evt.event === "tool_call"
                  ? "text-blue-400"
                  : evt.event === "tool_result"
                    ? statusColor(evt.data.status as string)
                    : "text-zinc-600"
              )}
            >
              {evt.event === "step_start"
                ? `STEP ${evt.data.step}`
                : evt.event.toUpperCase().replace("_", " ")}
            </span>
            <span className="text-zinc-400 truncate">
              {evt.event === "tool_call"
                ? (evt.data.tool as string)
                : evt.event === "tool_result"
                  ? `${evt.data.tool} → ${evt.data.status}`
                  : ""}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function statusColor(status: string): string {
  switch (status) {
    case "success":
      return "text-emerald-400";
    case "error":
      return "text-red-400";
    case "needs_approval":
      return "text-amber-400";
    default:
      return "text-zinc-400";
  }
}
