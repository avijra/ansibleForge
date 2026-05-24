import { useCallback, useMemo, useState } from "react";
import { Check, X, ShieldAlert, FileCode2, ArrowRight, CheckCircle2, XCircle, ChevronDown, ChevronRight } from "lucide-react";
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
  action?: string;
  detail?: string;
}

function parseDiffString(diff: string): { before: string; after: string } {
  const beforeMatch = diff.match(/^---\s*.*?\n([\s\S]*?)(?=\+\+\+)/m);
  const afterMatch = diff.match(/\+\+\+\s*.*?\n([\s\S]*)$/m);
  return {
    before: beforeMatch?.[1]?.trim() || "",
    after: afterMatch?.[1]?.trim() || "",
  };
}

function extractDiffs(event: AgentEvent): DiffBlock[] {
  const output = (event.data.output as string) || "";
  const diffs: DiffBlock[] = [];

  const nested = (event.data.data as Record<string, unknown>) ?? event.data;
  const diffSummary = nested.diff_summary as Record<string, unknown> | undefined;

  if (diffSummary) {
    const changes = (diffSummary.changes as Array<Record<string, unknown>>) || [];
    for (const c of changes) {
      let before = String(c.before || "");
      let after = String(c.after || "");

      if (!before && !after && c.diff) {
        const parsed = parseDiffString(String(c.diff));
        before = parsed.before;
        after = parsed.after;
      }

      diffs.push({
        host: String(c.host || ""),
        task: String(c.task || c.name || ""),
        before,
        after,
        action: String(c.action || ""),
        detail: String(c.detail || ""),
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

const RISK_STYLES: Record<string, { bg: string; text: string; border: string; label: string }> = {
  low: { bg: "bg-emerald-950/30", text: "text-emerald-400", border: "border-emerald-800/30", label: "LOW" },
  medium: { bg: "bg-amber-950/15", text: "text-amber-400", border: "border-amber-800/30", label: "MEDIUM" },
  high: { bg: "bg-orange-950/20", text: "text-orange-400", border: "border-orange-800/30", label: "HIGH" },
  critical: { bg: "bg-red-950/25", text: "text-red-400", border: "border-red-800/30", label: "CRITICAL" },
};

export function DiffReview({ event, isPending, onApprove, onReject }: DiffReviewProps) {
  const allDiffs = useMemo(() => extractDiffs(event), [event]);
  const output = (event.data.output as string) || "Execution requires your approval.";
  const [resolved, setResolved] = useState<"approved" | "rejected" | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");

  const nested = (event.data.data as Record<string, unknown>) ?? event.data;
  const riskLevel = ((nested.risk_level as string) || "").toLowerCase();
  const riskStyle = RISK_STYLES[riskLevel];
  const isCritical = riskLevel === "critical";

  const handleApprove = useCallback(() => {
    setResolved("approved");
    onApprove();
  }, [onApprove]);

  const handleReject = useCallback(() => {
    setResolved("rejected");
    onReject();
  }, [onReject]);

  const realDiffs = allDiffs.filter((d) => d.before.trim() || d.after.trim());
  const taskOnlyDiffs = allDiffs.filter((d) => !d.before.trim() && !d.after.trim() && d.task);

  const hasRealDiffs = realDiffs.length > 0;
  const hasTaskList = taskOnlyDiffs.length > 0;
  const actionCount = allDiffs.length;

  const showButtons = isPending && !resolved;
  const isResolved = resolved || !isPending;

  if (isResolved && !showButtons) {
    const label = resolved === "rejected" ? "Rejected" : "Approved";
    const Icon = resolved === "rejected" ? XCircle : CheckCircle2;
    const color = resolved === "rejected" ? "text-red-400" : "text-emerald-400";
    const border = resolved === "rejected" ? "border-red-800/20" : "border-emerald-800/20";
    return (
      <div className={cn("flex items-center gap-2 rounded-md border px-3 py-1.5 bg-zinc-900/40", border)}>
        <Icon className={cn("h-3.5 w-3.5", color)} />
        <span className={cn("text-xs font-medium", color)}>{label}</span>
        {actionCount > 0 && (
          <span className="text-[10px] text-zinc-600">
            · {actionCount} action{actionCount !== 1 ? "s" : ""}
          </span>
        )}
      </div>
    );
  }

  return (
    <div className={cn("animate-slide-in rounded-lg border shadow-[0_0_12px_-4px_rgba(245,158,11,0.12)] p-3 space-y-2", riskStyle?.border ?? "border-amber-800/30", riskStyle?.bg ?? "bg-amber-950/15")}>
      <div className="flex items-center gap-2">
        <ShieldAlert className={cn("h-3.5 w-3.5", riskStyle?.text ?? "text-amber-400")} />
        <span className="text-xs font-semibold text-amber-300">Approval Required</span>
        {riskStyle && (
          <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide", riskStyle.text, riskStyle.bg, "border", riskStyle.border)}>
            {riskStyle.label}
          </span>
        )}
        {actionCount > 0 && (
          <span className="text-[10px] text-amber-500/70">
            · {actionCount} action{actionCount !== 1 ? "s" : ""}
          </span>
        )}
        {(hasRealDiffs || hasTaskList || output) && (
          <button
            onClick={() => setDetailsOpen(!detailsOpen)}
            className="ml-auto flex items-center gap-1 text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            {detailsOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            Details
          </button>
        )}
      </div>

      {detailsOpen && (
        <>
          {hasRealDiffs && (
            <div className="space-y-2 max-h-60 overflow-y-auto">
              {realDiffs.map((block, i) => (
                <SideBySideDiff key={i} block={block} />
              ))}
            </div>
          )}

          {hasTaskList && (
            <TaskList diffs={taskOnlyDiffs} />
          )}

          {!hasRealDiffs && !hasTaskList && (
            <pre className="rounded-md bg-zinc-950/60 border border-zinc-800 p-2 text-[11px] font-mono text-zinc-300 overflow-x-auto whitespace-pre-wrap max-h-40 overflow-y-auto">
              {output}
            </pre>
          )}
        </>
      )}

      {isCritical && (
        <div className="flex items-center gap-2 rounded-md border border-red-800/30 bg-red-950/30 px-3 py-2">
          <span className="text-[11px] text-red-300">
            Type <strong>YES</strong> to confirm this critical operation:
          </span>
          <input
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder="YES"
            className="w-16 rounded border border-red-700/50 bg-red-950/50 px-2 py-0.5 text-xs text-red-200 placeholder-red-700 focus:border-red-500 focus:outline-none"
          />
        </div>
      )}

      <div className="flex items-center gap-2">
        <button
          onClick={handleApprove}
          disabled={isCritical && confirmText !== "YES"}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium text-white transition-colors",
            isCritical && confirmText !== "YES"
              ? "bg-zinc-700 cursor-not-allowed opacity-50"
              : "bg-emerald-600 hover:bg-emerald-500"
          )}
        >
          <Check className="h-3 w-3" />
          Approve
        </button>
        <button
          onClick={handleReject}
          className="inline-flex items-center gap-1.5 rounded-md bg-zinc-700 px-3 py-1 text-xs font-medium text-zinc-200 hover:bg-zinc-600 transition-colors"
        >
          <X className="h-3 w-3" />
          Reject
        </button>
        <span className="text-[10px] text-zinc-600 ml-auto">⌘⇧A</span>
      </div>
    </div>
  );
}
