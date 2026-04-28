import { useState } from "react";
import { CheckCircle2, XCircle, Clock, ChevronDown, ChevronRight, WifiOff } from "lucide-react";
import type { AgentEvent } from "@/api/types";
import { StatusBadge } from "@/components/common/StatusBadge";
import { TerminalOutput } from "@/components/common/TerminalOutput";
import { DiffView } from "@/components/common/DiffView";
import { cn } from "@/lib/utils";

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
      return <CheckCircle2 className="h-3 w-3 text-emerald-400 shrink-0" />;
    case "runner_on_changed":
      return <CheckCircle2 className="h-3 w-3 text-amber-400 shrink-0" />;
    case "runner_on_failed":
      return <XCircle className="h-3 w-3 text-red-400 shrink-0" />;
    case "runner_on_skipped":
      return <Clock className="h-3 w-3 text-zinc-500 shrink-0" />;
    case "runner_on_unreachable":
      return <WifiOff className="h-3 w-3 text-red-400 shrink-0" />;
    default:
      return <CheckCircle2 className="h-3 w-3 text-zinc-500 shrink-0" />;
  }
}

function taskLabel(eventType: string) {
  switch (eventType) {
    case "runner_on_ok": return "ok";
    case "runner_on_changed": return "changed";
    case "runner_on_failed": return "FAILED";
    case "runner_on_skipped": return "skipped";
    case "runner_on_unreachable": return "UNREACHABLE";
    default: return eventType.replace("runner_on_", "");
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
        <span
          className={cn(
            "text-[10px] font-mono px-1.5 py-0.5 rounded",
            task.event === "runner_on_ok" && "text-emerald-400 bg-emerald-500/10",
            task.event === "runner_on_changed" && "text-amber-400 bg-amber-500/10",
            task.event === "runner_on_failed" && "text-red-400 bg-red-500/10",
            task.event === "runner_on_skipped" && "text-zinc-500 bg-zinc-500/10",
            task.event === "runner_on_unreachable" && "text-red-400 bg-red-500/10"
          )}
        >
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
              <div className="text-[10px] text-zinc-500 mb-0.5 font-medium">stdout</div>
              <TerminalOutput content={String(stdout)} maxHeight="max-h-40" />
            </div>
          )}
          {!!stderr && (
            <div>
              <div className="text-[10px] text-red-400/70 mb-0.5 font-medium">stderr</div>
              <TerminalOutput
                content={String(stderr)}
                maxHeight="max-h-40"
                className="border-red-900/30 bg-red-950/20"
              />
            </div>
          )}
          {!!diffText && (
            <div>
              <div className="text-[10px] text-teal-400/70 mb-0.5 font-medium">diff</div>
              <DiffView content={diffText} maxHeight="max-h-48" />
            </div>
          )}
          {!!warnings?.length && (
            <div className="rounded bg-amber-950/10 border border-amber-900/20 px-2.5 py-1.5">
              <div className="text-[10px] text-amber-400/70 font-medium mb-1">
                warnings ({warnings.length})
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

function RecapBar({ stats }: { stats: Record<string, Record<string, number>> }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] font-mono">
      {Object.entries(stats).map(([host, counts]) => (
        <div key={host} className="flex items-center gap-2">
          <span className="text-zinc-400">{host}:</span>
          {counts.ok > 0 && <span className="text-emerald-400">ok={counts.ok}</span>}
          {counts.changed > 0 && <span className="text-amber-400">changed={counts.changed}</span>}
          {counts.failures > 0 && <span className="text-red-400">failed={counts.failures}</span>}
          {counts.unreachable > 0 && <span className="text-red-300">unreachable={counts.unreachable}</span>}
          {counts.skipped > 0 && <span className="text-zinc-500">skipped={counts.skipped}</span>}
        </div>
      ))}
    </div>
  );
}

export function ToolResultEvent({ event }: { event: AgentEvent }) {
  const tool = (event.data.tool as string) || "";
  const status = (event.data.status as string) || "success";
  const output = (event.data.output as string) || "";
  const data = event.data.data as Record<string, unknown> | undefined;

  const ansibleEvents = (data?.events as AnsibleTaskEvent[] | undefined) || [];
  const summary = data?.summary as AnsibleSummary | undefined;
  const hasAnsibleLogs = ansibleEvents.length > 0;

  const [logsOpen, setLogsOpen] = useState(hasAnsibleLogs);

  const Icon =
    status === "success"
      ? CheckCircle2
      : status === "needs_approval"
        ? Clock
        : XCircle;

  const borderColor =
    status === "success"
      ? "border-emerald-800/50"
      : status === "needs_approval"
        ? "border-amber-800/50"
        : "border-red-800/50";

  return (
    <div
      className={cn(
        "animate-slide-in rounded-lg border bg-zinc-900/50 p-3 space-y-2",
        borderColor
      )}
    >
      <div className="flex items-center gap-2">
        <Icon
          className={cn(
            "h-3.5 w-3.5",
            status === "success"
              ? "text-emerald-400"
              : status === "needs_approval"
                ? "text-amber-400"
                : "text-red-400"
          )}
        />
        <span className="text-xs font-mono text-zinc-400">{tool}</span>
        <StatusBadge status={status} className="ml-auto" />
      </div>

      {output && <TerminalOutput content={output} maxHeight="max-h-48" />}

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
              Ansible Log ({ansibleEvents.length} task{ansibleEvents.length !== 1 ? "s" : ""})
            </span>
          </button>

          {logsOpen && (
            <div className="space-y-0.5 rounded-md bg-zinc-950/60 border border-zinc-800 p-2 max-h-96 overflow-y-auto">
              {ansibleEvents.map((task, i) => (
                <TaskDetail key={i} task={task} />
              ))}
            </div>
          )}

          {summary?.stats && logsOpen && (
            <div className="rounded-md bg-zinc-950/40 border border-zinc-800 px-3 py-2">
              <div className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">Play Recap</div>
              <RecapBar stats={summary.stats} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
