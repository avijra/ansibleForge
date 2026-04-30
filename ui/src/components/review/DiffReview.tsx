import { useMemo } from "react";
import { Check, X, ShieldAlert, FileCode2, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AgentEvent } from "@/api/types";

interface DiffReviewProps {
  event: AgentEvent;
  isPending: boolean;
  onApprove: () => void;
  onReject: () => void;
}

interface DiffBlock {
  host: string;
  task: string;
  before: string;
  after: string;
}

function extractDiffs(event: AgentEvent): DiffBlock[] {
  const output = (event.data.output as string) || "";
  const diffs: DiffBlock[] = [];

  const nested = (event.data.data as Record<string, unknown>) ?? event.data;
  const diffSummary = nested.diff_summary as Record<string, unknown> | undefined;

  if (diffSummary) {
    const changes = (diffSummary.changes as Array<Record<string, unknown>>) || [];
    for (const c of changes) {
      diffs.push({
        host: String(c.host || ""),
        task: String(c.task || c.name || ""),
        before: String(c.before || ""),
        after: String(c.after || ""),
      });
    }
  }

  if (diffs.length === 0 && output) {
    const diffRegex = /---\s*(.*?)\n([\s\S]*?)\+\+\+\s*(.*?)\n([\s\S]*?)(?=---|\z)/g;
    let match: RegExpExecArray | null;
    while ((match = diffRegex.exec(output)) !== null) {
      diffs.push({
        host: "",
        task: match[1]?.trim() || "change",
        before: match[2]?.trim() || "",
        after: match[4]?.trim() || "",
      });
    }
  }

  return diffs;
}

function DiffLine({ line, side }: { line: string; side: "before" | "after" }) {
  const prefix = side === "before" ? "-" : "+";
  const color =
    side === "before"
      ? "text-red-400/90 bg-red-400/5"
      : "text-emerald-400/90 bg-emerald-400/5";

  return (
    <div className={cn("px-3 py-0.5 text-[11px] font-mono", color)}>
      <span className="select-none opacity-50 mr-2">{prefix}</span>
      {line}
    </div>
  );
}

function SideBySideDiff({ block }: { block: DiffBlock }) {
  const beforeLines = block.before.split("\n").filter(Boolean);
  const afterLines = block.after.split("\n").filter(Boolean);
  const maxLen = Math.max(beforeLines.length, afterLines.length);

  return (
    <div className="rounded-md border border-zinc-800 overflow-hidden">
      {(block.host || block.task) && (
        <div className="flex items-center gap-2 bg-zinc-900/80 px-3 py-1.5 border-b border-zinc-800">
          <FileCode2 className="h-3 w-3 text-zinc-500" />
          {block.host && (
            <span className="text-[11px] font-mono text-zinc-400">{block.host}</span>
          )}
          {block.host && block.task && (
            <span className="text-zinc-700">/</span>
          )}
          {block.task && (
            <span className="text-[11px] text-zinc-500">{block.task}</span>
          )}
        </div>
      )}
      <div className="grid grid-cols-2 divide-x divide-zinc-800">
        <div className="min-w-0">
          <div className="px-3 py-1 text-[10px] text-red-400/60 border-b border-zinc-800/50 bg-red-950/10">
            Before
          </div>
          {Array.from({ length: maxLen }, (_, i) => (
            <DiffLine
              key={`b-${i}`}
              line={beforeLines[i] || ""}
              side="before"
            />
          ))}
          {beforeLines.length === 0 && (
            <div className="px-3 py-2 text-[11px] text-zinc-600 italic">
              (empty)
            </div>
          )}
        </div>
        <div className="min-w-0">
          <div className="px-3 py-1 text-[10px] text-emerald-400/60 border-b border-zinc-800/50 bg-emerald-950/10">
            After
          </div>
          {Array.from({ length: maxLen }, (_, i) => (
            <DiffLine
              key={`a-${i}`}
              line={afterLines[i] || ""}
              side="after"
            />
          ))}
          {afterLines.length === 0 && (
            <div className="px-3 py-2 text-[11px] text-zinc-600 italic">
              (empty)
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function TaskList({ diffs }: { diffs: DiffBlock[] }) {
  return (
    <div className="rounded-md border border-zinc-800 overflow-hidden divide-y divide-zinc-800/50">
      {diffs.map((block, i) => (
        <div key={i} className="flex items-center gap-2.5 px-3 py-2 bg-zinc-900/50">
          <ArrowRight className="h-3 w-3 text-amber-500/70 shrink-0" />
          <span className="text-[11px] text-zinc-300">{block.task}</span>
          {block.host && (
            <span className="ml-auto text-[10px] font-mono text-zinc-600">
              {block.host}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

export function DiffReview({ event, isPending, onApprove, onReject }: DiffReviewProps) {
  const allDiffs = useMemo(() => extractDiffs(event), [event]);
  const output = (event.data.output as string) || "Execution requires your approval.";

  const realDiffs = allDiffs.filter((d) => d.before.trim() || d.after.trim());
  const taskOnlyDiffs = allDiffs.filter((d) => !d.before.trim() && !d.after.trim() && d.task);

  const hasRealDiffs = realDiffs.length > 0;
  const hasTaskList = taskOnlyDiffs.length > 0;

  return (
    <div className="animate-slide-in rounded-lg border border-amber-800/30 bg-amber-950/15 shadow-[0_0_12px_-4px_rgba(245,158,11,0.12)] p-4 space-y-3">
      <div className="flex items-center gap-2">
        <ShieldAlert className="h-4 w-4 text-amber-400" />
        <span className="text-sm font-semibold text-amber-300">
          Approval Required
        </span>
        {(hasRealDiffs || hasTaskList) && (
          <span className="text-[10px] text-amber-500/70 ml-auto">
            {allDiffs.length} action{allDiffs.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {hasRealDiffs && (
        <div className="space-y-2 max-h-80 overflow-y-auto">
          {realDiffs.map((block, i) => (
            <SideBySideDiff key={i} block={block} />
          ))}
        </div>
      )}

      {hasTaskList && (
        <TaskList diffs={taskOnlyDiffs} />
      )}

      {!hasRealDiffs && !hasTaskList && (
        <pre className="rounded-md bg-zinc-950/60 border border-zinc-800 p-3 text-xs font-mono text-zinc-300 overflow-x-auto whitespace-pre-wrap max-h-64 overflow-y-auto">
          {output}
        </pre>
      )}

      {isPending && (
        <div className="flex items-center gap-2 pt-1">
          <button
            onClick={onApprove}
            className="inline-flex items-center gap-1.5 rounded-md bg-emerald-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-emerald-500 transition-colors"
          >
            <Check className="h-3.5 w-3.5" />
            Approve
          </button>
          <button
            onClick={onReject}
            className="inline-flex items-center gap-1.5 rounded-md bg-zinc-700 px-4 py-1.5 text-xs font-medium text-zinc-200 hover:bg-zinc-600 transition-colors"
          >
            <X className="h-3.5 w-3.5" />
            Reject
          </button>
          <span className="text-[10px] text-zinc-600 ml-auto">
            ⌘⇧A approve
          </span>
        </div>
      )}
    </div>
  );
}
