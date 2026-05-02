import { useState } from "react";
import { AlertTriangle, Lightbulb, ChevronDown, ChevronRight } from "lucide-react";
import type { AgentEvent } from "@/api/types";
import { friendlyToolName } from "@/lib/tool-labels";

const causeLabels: Record<string, string> = {
  auth: "Authentication failed",
  rate_limit: "Rate limit exceeded — please wait a moment",
  model_not_found: "AI model not available",
  timeout: "Request timed out",
  connection: "Connection failed",
  quota: "Quota or billing issue",
  parse_error: "Could not understand the response",
  validation: "Invalid input",
  permission: "Permission denied",
};

function humanSummary(error: string, tool?: string): string {
  if (error.includes("Loop detected") || error.includes("stuck repeating"))
    return "The agent appears to be stuck repeating the same action.";
  if (error.includes("Soft loop") || error.includes("same type of action"))
    return "The agent has been running the same type of action many times — checking if this is intentional.";
  if (error.includes("empty response") || error.includes("returned no response"))
    return "The AI model returned no response. Retrying with a simpler approach.";
  if (error.includes("timed out"))
    return tool
      ? `${friendlyToolName(tool)} timed out. The request took too long to complete.`
      : "The request timed out. It may have been too complex.";
  if (error.includes("context may be too large"))
    return "The conversation has grown too large for the AI model. Consider starting a new chat.";
  if (error.length > 200) return error.slice(0, 150) + "…";
  return error;
}

export function ErrorEvent({ event }: { event: AgentEvent }) {
  const error =
    (event.data.error as string) || (event.data.message as string) || "Unknown error";
  const tool = event.data.tool as string | undefined;
  const hint = event.data.hint as string | undefined;
  const cause = event.data.cause as string | undefined;
  const [showDetails, setShowDetails] = useState(false);

  const label = cause && causeLabels[cause]
    ? causeLabels[cause]
    : tool
      ? `Error in ${friendlyToolName(tool)}`
      : "Error";

  const summary = humanSummary(error, tool);
  const hasTechnicalDetails = summary !== error;

  return (
    <div className="animate-slide-in rounded-lg border border-red-800/30 bg-red-950/15 shadow-[0_0_12px_-4px_rgba(239,68,68,0.12)] p-3 space-y-2">
      <div className="flex items-center gap-2">
        <AlertTriangle className="h-3.5 w-3.5 text-zinc-400" />
        <span className="text-xs font-medium text-zinc-400">{label}</span>
      </div>
      <p className="text-xs text-zinc-400/80 whitespace-pre-wrap">{summary}</p>
      {hasTechnicalDetails && (
        <>
          <button
            onClick={() => setShowDetails(!showDetails)}
            className="flex items-center gap-1 text-[10px] text-zinc-600 hover:text-zinc-400 transition-colors"
          >
            {showDetails
              ? <ChevronDown className="h-3 w-3" />
              : <ChevronRight className="h-3 w-3" />
            }
            <span>Technical Details</span>
          </button>
          {showDetails && (
            <pre className="rounded bg-zinc-950/60 border border-zinc-800 px-2 py-1.5 text-[11px] font-mono text-zinc-500 whitespace-pre-wrap">
              {error}
            </pre>
          )}
        </>
      )}
      {hint && (
        <div className="flex items-start gap-2 rounded-md bg-zinc-900/50 px-2.5 py-2 border border-zinc-800/50">
          <Lightbulb className="h-3 w-3 text-amber-500/70 mt-0.5 shrink-0" />
          <p className="text-[11px] text-zinc-400">{hint}</p>
        </div>
      )}
    </div>
  );
}
