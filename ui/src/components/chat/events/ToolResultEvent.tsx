import { useState } from "react";
import { CheckCircle2, XCircle, Clock, ChevronDown, ChevronRight, WifiOff } from "lucide-react";
import type { AgentEvent } from "@/api/types";
import { StatusBadge } from "@/components/common/StatusBadge";
import { TerminalOutput } from "@/components/common/TerminalOutput";
import { DiffView } from "@/components/common/DiffView";
import { cn } from "@/lib/utils";
import { friendlyToolName } from "@/lib/tool-labels";

interface AnsibleTaskEvent {
  event: string;
  host: string;
  task: string;
  result?: Record<string, unknown>;
}

interface AnsibleSummary {
  status: string;
  rc: number;
  stats: Record<string, Record<string, number>>;
  event_count: number;
}

function taskIcon(eventType: string) {
  switch (eventType) {
    case "runner_on_ok":
      return <CheckCircle2 className="h-3 w-3 text-emerald-500/70 shrink-0" />;
    case "runner_on_changed":
      return <CheckCircle2 className="h-3 w-3 text-amber-400/70 shrink-0" />;
    case "runner_on_failed":
      return <XCircle className="h-3 w-3 text-red-400/70 shrink-0" />;
    case "runner_on_skipped":
      return <Clock className="h-3 w-3 text-zinc-600 shrink-0" />;
    case "runner_on_unreachable":
      return <WifiOff className="h-3 w-3 text-red-400/70 shrink-0" />;
    default:
      return <CheckCircle2 className="h-3 w-3 text-zinc-600 shrink-0" />;
  }
}

function taskLabel(eventType: string): string {
  switch (eventType) {
    case "runner_on_ok": return "done";
    case "runner_on_changed": return "changed";
    case "runner_on_failed": return "failed";
    case "runner_on_skipped": return "skipped";
    case "runner_on_unreachable": return "unreachable";
    default: return eventType.replace("runner_on_", "");
  }
}

function taskLabelColor(eventType: string): string {
  switch (eventType) {
    case "runner_on_ok": return "text-emerald-400/80 bg-emerald-950/30";
    case "runner_on_changed": return "text-amber-400/80 bg-amber-950/30";
    case "runner_on_failed": return "text-red-400/80 bg-red-950/30";
    case "runner_on_skipped": return "text-zinc-600 bg-zinc-800/30";
    case "runner_on_unreachable": return "text-red-400/80 bg-red-950/30";
    default: return "text-zinc-500 bg-zinc-800/30";
  }
}

function formatDiff(diff: unknown): string | null {
  if (!diff) return null;
  if (typeof diff === "string") return diff;
  if (typeof diff === "object" && diff !== null) {
    const d = diff as Record<string, unknown>;
    const parts: string[] = [];
    if (d.before) parts.push(`--- before\n${String(d.before)}`);
    if (d.after) parts.push(`+++ after\n${String(d.after)}`);
    if (d.prepared) return String(d.prepared);
    if (parts.length > 0) return parts.join("\n");
    return JSON.stringify(diff, null, 2);
  }
  return String(diff);
}

function TaskDetail({ task }: { task: AnsibleTaskEvent }) {
  const defaultOpen =
    task.event === "runner_on_failed" ||
    task.event === "runner_on_changed" ||
    task.event === "runner_on_unreachable";
  const [open, setOpen] = useState(defaultOpen);
  const res = task.result || {};
  const diffText = formatDiff(res.diff);
  const stdout = (res.stdout || res.module_stdout) as string | undefined;
  const stderr = (res.stderr || res.module_stderr) as string | undefined;
  const warnings = res.warnings as string[] | undefined;
  const hasDetail = !!(res.msg || stdout || stderr || diffText || warnings?.length);

  return (
    <div className="border-l-2 border-zinc-800 pl-3 py-1">
      <button
        onClick={() => hasDetail && setOpen(!open)}
        className={cn(
          "flex items-center gap-2 w-full text-left",
          hasDetail ? "cursor-pointer hover:bg-zinc-800/30 -ml-3 pl-3 rounded" : "cursor-default"
        )}
      >
        {taskIcon(task.event)}
        <span className="text-xs text-zinc-300 truncate flex-1">{task.task || "unknown"}</span>
        <span className="text-[10px] text-zinc-500 font-mono">{task.host}</span>
        <span className={cn("text-[10px] px-1.5 py-0.5 rounded", taskLabelColor(task.event))}>
          {taskLabel(task.event)}
        </span>
        {hasDetail && (
          open
            ? <ChevronDown className="h-3 w-3 text-zinc-500 shrink-0" />
            : <ChevronRight className="h-3 w-3 text-zinc-500 shrink-0" />
        )}
      </button>

      {open && hasDetail && (
        <div className="mt-1.5 space-y-1.5 animate-slide-in">
          {!!res.msg && (
            <pre className="rounded bg-zinc-950/60 border border-zinc-800 px-2 py-1 text-[11px] font-mono text-zinc-400 whitespace-pre-wrap">
              {String(res.msg)}
            </pre>
          )}
          {!!stdout && (
            <div>
              <div className="text-[10px] text-zinc-500 mb-0.5 font-medium">Output</div>
              <TerminalOutput content={String(stdout)} maxHeight="max-h-40" />
            </div>
          )}
          {!!stderr && (
            <div>
              <div className="text-[10px] text-red-400/70 mb-0.5 font-medium">Errors</div>
              <TerminalOutput
                content={String(stderr)}
                maxHeight="max-h-40"
                className="border-red-900/30 bg-red-950/20"
              />
            </div>
          )}
          {!!diffText && (
            <div>
              <div className="text-[10px] text-zinc-400 mb-0.5 font-medium">Changes</div>
              <DiffView content={diffText} maxHeight="max-h-48" />
            </div>
          )}
          {!!warnings?.length && (
            <div className="rounded bg-amber-950/10 border border-amber-900/20 px-2.5 py-1.5">
              <div className="text-[10px] text-amber-400/70 font-medium mb-1">
                Warnings ({warnings.length})
              </div>
              <pre className="text-[11px] font-mono text-amber-300/80 whitespace-pre-wrap">
                {warnings.map(String).join("\n")}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function explainConcept(text: string): string | null {
  const lower = text.toLowerCase();
  if (lower.includes("check mode") || lower.includes("dry-run") || lower.includes("dry run") || lower.includes("preview"))
    return "Preview only — no changes were made to any servers.";
  if (lower.includes("become") && (lower.includes("true") || lower.includes("elevated")))
    return "Running with elevated (admin/root) privileges.";
  if (lower.includes("gathering facts") || lower.includes("collect_facts") || lower.includes("setup module"))
    return "Collecting system details like OS version, memory, and network configuration.";
  if (lower.includes("inventory") && (lower.includes("created") || lower.includes("writing") || lower.includes("managing")))
    return "The server list that defines which machines to manage.";
  if (lower.includes("playbook") && (lower.includes("generat") || lower.includes("writing")))
    return "An automated script that defines what to configure on your servers.";
  if (lower.includes("role") && lower.includes("scaffold"))
    return "A reusable package of automation tasks, files, and templates.";
  if (lower.includes("vault") && (lower.includes("encrypt") || lower.includes("decrypt")))
    return "Securely storing sensitive data like passwords and keys.";
  return null;
}

function hasNonZeroStats(stats: Record<string, Record<string, number>>): boolean {
  return Object.values(stats).some((counts) =>
    Object.values(counts).some((v) => v > 0)
  );
}

function RecapBar({ stats }: { stats: Record<string, Record<string, number>> }) {
  if (!hasNonZeroStats(stats)) return null;
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
      {Object.entries(stats).map(([host, counts]) => {
        const hasValues = Object.values(counts).some((v) => v > 0);
        if (!hasValues) return null;
        const parts: string[] = [];
        if (counts.ok > 0) parts.push(`${counts.ok} completed`);
        if (counts.changed > 0) parts.push(`${counts.changed} changed`);
        if (counts.failures > 0) parts.push(`${counts.failures} failed`);
        if (counts.unreachable > 0) parts.push(`${counts.unreachable} unreachable`);
        if (counts.skipped > 0) parts.push(`${counts.skipped} skipped`);
        return (
          <div key={host} className="flex items-center gap-1.5">
            <span className="text-zinc-400 font-medium">{host}:</span>
            <span className="text-zinc-500">{parts.join(", ")}</span>
          </div>
        );
      })}
    </div>
  );
}

function extractAdhocOutput(data: Record<string, unknown> | undefined): string | null {
  if (!data) return null;
  const hostResults = data.host_results as Record<string, Record<string, unknown>> | undefined;
  if (!hostResults) return null;
  const parts: string[] = [];
  for (const [host, result] of Object.entries(hostResults)) {
    const stdout = (result.stdout || result.module_stdout) as string | undefined;
    const stderr = (result.stderr || result.module_stderr) as string | undefined;
    if (!stdout && !stderr) continue;
    const prefix = Object.keys(hostResults).length > 1 ? `[${host}] ` : "";
    if (stdout?.trim()) parts.push(`${prefix}${stdout.trim()}`);
    if (stderr?.trim() && result.rc !== 0) parts.push(`${prefix}⚠ ${stderr.trim()}`);
  }
  return parts.length > 0 ? parts.join("\n") : null;
}

export function ToolResultEvent({ event }: { event: AgentEvent }) {
  const tool = (event.data.tool as string) || "";
  const status = (event.data.status as string) || "success";
  const output = (event.data.output as string) || "";
  const data = event.data.data as Record<string, unknown> | undefined;

  const ansibleEvents = (data?.events as AnsibleTaskEvent[] | undefined) || [];
  const summary = data?.summary as AnsibleSummary | undefined;
  const hasAnsibleLogs = ansibleEvents.length > 0;
  const adhocOutput = tool === "run_adhoc" ? extractAdhocOutput(data) : null;

  const [logsOpen, setLogsOpen] = useState(hasAnsibleLogs);

  const Icon =
    status === "success"
      ? CheckCircle2
      : status === "needs_approval"
        ? Clock
        : XCircle;

  const borderColor =
    status === "success"
      ? "border-emerald-800/30 shadow-[0_0_12px_-4px_rgba(16,185,129,0.10)]"
      : status === "needs_approval"
        ? "border-amber-800/30 shadow-[0_0_12px_-4px_rgba(245,158,11,0.10)]"
        : "border-red-800/30 shadow-[0_0_12px_-4px_rgba(239,68,68,0.10)]";

  return (
    <div
      className={cn(
        "animate-slide-in rounded-lg border bg-zinc-900/40 p-3 space-y-2",
        borderColor
      )}
    >
      <div className="flex items-center gap-2">
        <Icon className="h-3.5 w-3.5 text-zinc-500" />
        <span className="text-xs text-zinc-400">{friendlyToolName(tool)}</span>
        <StatusBadge status={status} className="ml-auto" />
      </div>

      {adhocOutput ? (
        <TerminalOutput content={adhocOutput} maxHeight="max-h-48" />
      ) : output ? (() => {
        const cleaned = output.replace(/\nPLAY RECAP[\s\S]*$/, "").trim();
        if (!cleaned) return null;
        const hint = explainConcept(cleaned);
        return (
          <>
            <TerminalOutput content={cleaned} maxHeight="max-h-48" />
            {hint && (
              <p className="text-[11px] text-zinc-600 italic px-0.5">{hint}</p>
            )}
          </>
        );
      })() : null}

      {hasAnsibleLogs && (
        <div className="space-y-2">
          <button
            onClick={() => setLogsOpen(!logsOpen)}
            className="flex items-center gap-1.5 text-[11px] text-zinc-400 hover:text-zinc-300 transition-colors"
          >
            {logsOpen
              ? <ChevronDown className="h-3.5 w-3.5" />
              : <ChevronRight className="h-3.5 w-3.5" />
            }
            <span className="font-medium">
              Execution Log ({ansibleEvents.length} step{ansibleEvents.length !== 1 ? "s" : ""})
            </span>
          </button>

          {logsOpen && (
            <div className="space-y-0.5 rounded-md bg-zinc-950/60 border border-zinc-800 p-2 max-h-96 overflow-y-auto">
              {ansibleEvents.map((task, i) => (
                <TaskDetail key={i} task={task} />
              ))}
            </div>
          )}

          {summary?.stats && logsOpen && hasNonZeroStats(summary.stats) && (
            <div className="rounded-md bg-zinc-950/40 border border-zinc-800 px-3 py-2">
              <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">Results Summary</div>
              <RecapBar stats={summary.stats} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
