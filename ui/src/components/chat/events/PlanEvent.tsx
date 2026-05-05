import { useState } from "react";
import {
  ListChecks,
  ChevronDown,
  ChevronRight,
  Circle,
  CheckCircle2,
  Loader2,
  SkipForward,
} from "lucide-react";
import type { AgentEvent } from "@/api/types";
import { cn } from "@/lib/utils";

interface PlanStep {
  step: number;
  action: string;
  tool?: string;
  status?: "pending" | "running" | "done" | "skipped";
}

interface PlanEventProps {
  event: AgentEvent;
  completedTools?: string[];
  isStale?: boolean;
}

function stepIcon(status: string) {
  switch (status) {
    case "done":
      return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />;
    case "running":
      return <Loader2 className="h-3.5 w-3.5 text-blue-400 animate-spin" />;
    case "skipped":
      return <SkipForward className="h-3.5 w-3.5 text-zinc-600" />;
    default:
      return <Circle className="h-3.5 w-3.5 text-zinc-700" />;
  }
}

export function PlanEvent({ event, completedTools = [], isStale = false }: PlanEventProps) {
  const [expanded, setExpanded] = useState(!isStale);
  const steps: PlanStep[] = (event.data.steps as PlanStep[]) || [];

  if (steps.length === 0) return null;

  const stepsWithStatus = steps.map((s) => {
    if (s.status) return s;
    const toolDone = s.tool && completedTools.includes(s.tool);
    return { ...s, status: toolDone ? "done" as const : "pending" as const };
  });

  const doneCount = stepsWithStatus.filter((s) => s.status === "done").length;

  return (
    <div className="animate-slide-in rounded-lg border border-zinc-800 bg-zinc-900/50 p-3 space-y-2">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 text-left"
      >
        <ListChecks className="h-4 w-4 text-blue-400" />
        <span className="text-xs font-semibold text-zinc-300">
          Plan
        </span>
        <span className="text-[10px] text-zinc-600">
          {doneCount}/{steps.length} steps
        </span>
        <div className="ml-auto">
          {expanded ? (
            <ChevronDown className="h-3.5 w-3.5 text-zinc-600" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-zinc-600" />
          )}
        </div>
      </button>

      {expanded && (
        <div className="space-y-1 ml-1">
          {stepsWithStatus.map((s, i) => (
            <div
              key={i}
              className={cn(
                "flex items-start gap-2 py-1 px-2 rounded text-xs",
                s.status === "done" && "opacity-60",
                s.status === "running" && "bg-blue-950/20"
              )}
            >
              {stepIcon(s.status || "pending")}
              <div className="flex-1 min-w-0">
                <span className="text-zinc-300">{s.action}</span>
                {s.tool && (
                  <span className="ml-1.5 text-[10px] font-mono text-zinc-600">
                    {s.tool}
                  </span>
                )}
              </div>
              <span className="text-[10px] text-zinc-700 shrink-0">#{s.step}</span>
            </div>
          ))}
        </div>
      )}

      {doneCount > 0 && doneCount < steps.length && (
        <div className="h-1 bg-zinc-800 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-500 transition-all duration-500 rounded-full"
            style={{ width: `${(doneCount / steps.length) * 100}%` }}
          />
        </div>
      )}
    </div>
  );
}
