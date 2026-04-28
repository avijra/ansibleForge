import { ShieldAlert, Check, X } from "lucide-react";
import type { AgentEvent } from "@/api/types";

interface ApprovalEventProps {
  event: AgentEvent;
  isPending: boolean;
  onApprove: () => void;
  onReject: () => void;
}

export function ApprovalEvent({
  event,
  isPending,
  onApprove,
  onReject,
}: ApprovalEventProps) {
  const output = (event.data.output as string) || "Execution requires your approval.";

  return (
    <div className="animate-slide-in rounded-lg border-2 border-amber-700/60 bg-amber-950/20 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <ShieldAlert className="h-4 w-4 text-amber-400" />
        <span className="text-sm font-semibold text-amber-300">
          Approval Required
        </span>
      </div>

      <pre className="rounded-md bg-zinc-950/60 border border-zinc-800 p-3 text-xs font-mono text-zinc-300 overflow-x-auto whitespace-pre-wrap max-h-64 overflow-y-auto">
        {output}
      </pre>

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
        </div>
      )}
    </div>
  );
}
