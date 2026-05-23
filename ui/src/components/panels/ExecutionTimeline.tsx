import { useState, useMemo, useRef, useEffect, useCallback } from "react";
import {
  CheckCircle2,
  XCircle,
  Circle,
  Clock,
  Loader2,
  MinusCircle,
  WifiOff,
  ChevronDown,
  ChevronRight,
  FileCode2,
  Filter,
  Play,
  AlertTriangle,
  ScrollText,
  Terminal,
  Wrench,
} from "lucide-react";
import type { AgentEvent } from "@/api/types";
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

interface DetectedLog {
  path: string;
  size: string;
  preview: string;
}

interface ExecutionRun {
  id: string;
  tool: string;
  status: string;
  mode: string;
  tasks: AnsibleTaskEvent[];
  summary?: AnsibleSummary;
  timestamp: number;
  playbook?: string;
  rawStdout?: string;
  detectedLogs?: DetectedLog[];
}

type StatusFilter = "ok" | "changed" | "failed" | "skipped" | "unreachable";

const STATUS_MAP: Record<string, StatusFilter> = {
  runner_on_ok: "ok",
  runner_on_changed: "changed",
  runner_on_failed: "failed",
  runner_on_skipped: "skipped",
  runner_on_unreachable: "unreachable",
};

function extractAdhocTasks(data: Record<string, unknown>): AnsibleTaskEvent[] {
  const hostResults = data.host_results as Record<string, Record<string, unknown>> | undefined;
  if (!hostResults) return [];
  const module = (data.module as string) || "shell";
  const moduleArgs = (data.module_args as string) || "";
  const label = moduleArgs.length > 60 ? moduleArgs.slice(0, 60) + "..." : moduleArgs || module;

  return Object.entries(hostResults).map(([host, result]) => {
    const status = result.status as string;
    const eventType = status === "ok" ? "runner_on_ok"
      : status === "failed" ? "runner_on_failed"
      : status === "unreachable" ? "runner_on_unreachable"
      : "runner_on_ok";
    return {
      event: eventType,
      host,
      task: label,
      result: result as Record<string, unknown>,
    };
  });
}

function extractRuns(events: AgentEvent[]): ExecutionRun[] {
  const runs: ExecutionRun[] = [];
  for (const ev of events) {
    if (ev.event !== "tool_result") continue;
    const tool = (ev.data.tool as string) || "";
    const data = ev.data.data as Record<string, unknown> | undefined;
    if (!data) continue;

    if (tool === "run_adhoc") {
      const tasks = extractAdhocTasks(data);
      if (tasks.length === 0) continue;
      const module = (data.module as string) || "shell";
      const moduleArgs = (data.module_args as string) || "";
      const label = moduleArgs.length > 60 ? moduleArgs.slice(0, 60) + "..." : moduleArgs || module;
      runs.push({
        id: ev.id,
        tool,
        status: (ev.data.status as string) || "success",
        mode: "adhoc",
        tasks,
        timestamp: ev.timestamp,
        playbook: `adhoc: ${label}`,
      });
      continue;
    }

    const tasks = (data.events as AnsibleTaskEvent[] | undefined) || [];
    if (tasks.length === 0) continue;

    const mode = (data.mode as string) || "check";
    const playbook = (data.playbook as string) || undefined;

    runs.push({
      id: ev.id,
      tool: tool || "execute_playbook",
      status: (ev.data.status as string) || "success",
      mode,
      tasks,
      summary: data.summary as AnsibleSummary | undefined,
      timestamp: ev.timestamp,
      playbook,
      rawStdout: (data.raw_stdout as string) || undefined,
      detectedLogs: (data.detected_logs as DetectedLog[] | undefined) || undefined,
    });
  }
  return runs;
}

function StatusIcon({ event }: { event: string }) {
  switch (event) {
    case "runner_on_ok":
      return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 shrink-0" />;
    case "runner_on_changed":
      return <AlertTriangle className="h-3.5 w-3.5 text-amber-400 shrink-0" />;
    case "runner_on_failed":
      return <XCircle className="h-3.5 w-3.5 text-red-400 shrink-0" />;
    case "runner_on_skipped":
      return <Clock className="h-3.5 w-3.5 text-zinc-500 shrink-0" />;
    case "runner_on_unreachable":
      return <WifiOff className="h-3.5 w-3.5 text-orange-400 shrink-0" />;
    default:
      return <CheckCircle2 className="h-3.5 w-3.5 text-zinc-500 shrink-0" />;
  }
}

function statusLabel(event: string): string {
  switch (event) {
    case "runner_on_ok": return "OK";
    case "runner_on_changed": return "CHANGED";
    case "runner_on_failed": return "FAILED";
    case "runner_on_skipped": return "SKIPPED";
    case "runner_on_unreachable": return "UNREACHABLE";
    default: return event.replace("runner_on_", "").toUpperCase();
  }
}

function statusColor(event: string): string {
  switch (event) {
    case "runner_on_ok": return "text-emerald-400";
    case "runner_on_changed": return "text-amber-400";
    case "runner_on_failed": return "text-red-400";
    case "runner_on_skipped": return "text-zinc-500";
    case "runner_on_unreachable": return "text-orange-400";
    default: return "text-zinc-500";
  }
}

function connectorColor(event: string): string {
  switch (event) {
    case "runner_on_ok": return "border-emerald-800/60";
    case "runner_on_changed": return "border-amber-800/60";
    case "runner_on_failed": return "border-red-800/60";
    case "runner_on_skipped": return "border-zinc-800/60";
    case "runner_on_unreachable": return "border-orange-800/60";
    default: return "border-zinc-800/60";
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

function TaskNode({
  task,
  isLast,
  isActive,
}: {
  task: AnsibleTaskEvent;
  isLast: boolean;
  isActive: boolean;
}) {
  const shouldExpand =
    task.event === "runner_on_failed" ||
    task.event === "runner_on_changed" ||
    task.event === "runner_on_unreachable";
  const [expanded, setExpanded] = useState(shouldExpand);

  const res = task.result || {};
  const diffText = formatDiff(res.diff);
  const stdout = (res.stdout || res.module_stdout) as string | undefined;
  const stderr = (res.stderr || res.module_stderr) as string | undefined;
  const msg = res.msg as string | undefined;
  const warnings = res.warnings as string[] | undefined;
  const hasDetail = !!(msg || stdout || stderr || diffText || warnings?.length);

  return (
    <div className="relative">
      {/* Connector line */}
      {!isLast && (
        <div
          className={cn(
            "absolute left-[9px] top-[22px] bottom-0 w-px border-l-2",
            connectorColor(task.event)
          )}
        />
      )}

      {/* Task row */}
      <div className="flex items-start gap-3 group">
        {/* Node dot */}
        <div className={cn("relative mt-[3px] shrink-0", isActive && "animate-pulse-dot")}>
          <StatusIcon event={task.event} />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0 pb-4">
          <button
            onClick={() => hasDetail && setExpanded(!expanded)}
            className={cn(
              "flex items-center gap-2 w-full text-left rounded px-1.5 py-0.5 -ml-1.5",
              hasDetail && "hover:bg-zinc-800/50 cursor-pointer",
              !hasDetail && "cursor-default"
            )}
          >
            <span className="text-xs text-zinc-200 font-medium truncate flex-1">
              {task.task || "unnamed task"}
            </span>
            <span className="text-[10px] font-mono text-zinc-500 shrink-0">
              {task.host}
            </span>
            <span
              className={cn(
                "text-[10px] font-mono font-medium shrink-0",
                statusColor(task.event)
              )}
            >
              {statusLabel(task.event)}
            </span>
            {hasDetail && (
              expanded
                ? <ChevronDown className="h-3 w-3 text-zinc-600 shrink-0" />
                : <ChevronRight className="h-3 w-3 text-zinc-600 shrink-0" />
            )}
          </button>

          {/* Detail panel */}
          {expanded && hasDetail && (
            <div className="mt-1.5 ml-0 space-y-1.5 animate-slide-in min-w-0 overflow-hidden">
              {!!msg && (
                <div className="rounded bg-zinc-900 border border-zinc-800 px-2.5 py-1.5 text-[11px] font-mono text-zinc-400 whitespace-pre-wrap">
                  {msg}
                </div>
              )}
              {!!stdout && (
                <div className="rounded bg-zinc-900 border border-zinc-800 overflow-hidden">
                  <div className="px-2.5 py-1 text-[10px] text-zinc-500 bg-zinc-900 border-b border-zinc-800 font-medium">
                    stdout
                  </div>
                  <pre className="px-2.5 py-1.5 text-[11px] font-mono text-zinc-400 whitespace-pre-wrap max-h-48 overflow-y-auto">
                    {stdout}
                  </pre>
                </div>
              )}
              {!!stderr && (
                <div className="rounded bg-red-950/20 border border-red-900/30 overflow-hidden">
                  <div className="px-2.5 py-1 text-[10px] text-red-400/70 bg-red-950/30 border-b border-red-900/30 font-medium">
                    stderr
                  </div>
                  <pre className="px-2.5 py-1.5 text-[11px] font-mono text-red-300/80 whitespace-pre-wrap max-h-48 overflow-y-auto">
                    {stderr}
                  </pre>
                </div>
              )}
              {!!diffText && (
                <div className="rounded bg-zinc-900 border border-zinc-800 overflow-hidden">
                  <div className="px-2.5 py-1 text-[10px] text-zinc-400 bg-zinc-900 border-b border-zinc-800 font-medium">
                    diff
                  </div>
                  <pre className="px-2.5 py-1.5 text-[11px] font-mono whitespace-pre-wrap max-h-48 overflow-y-auto">
                    {diffText.split("\n").map((line, i) => (
                      <span
                        key={i}
                        className={cn(
                          "block",
                          line.startsWith("+") && !line.startsWith("+++") && "text-emerald-400 bg-emerald-500/5",
                          line.startsWith("-") && !line.startsWith("---") && "text-red-400 bg-red-500/5",
                          !line.startsWith("+") && !line.startsWith("-") && "text-zinc-500"
                        )}
                      >
                        {line}
                      </span>
                    ))}
                  </pre>
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
      </div>
    </div>
  );
}

function RecapBar({ stats }: { stats: Record<string, Record<string, number>> }) {
  const totals = useMemo(() => {
    const t = { ok: 0, changed: 0, failures: 0, unreachable: 0, skipped: 0 };
    for (const counts of Object.values(stats)) {
      t.ok += counts.ok || 0;
      t.changed += counts.changed || 0;
      t.failures += counts.failures || 0;
      t.unreachable += counts.unreachable || 0;
      t.skipped += counts.skipped || 0;
    }
    return t;
  }, [stats]);

  const total = totals.ok + totals.changed + totals.failures + totals.unreachable + totals.skipped;
  if (total === 0) return null;

  const segments = [
    { key: "ok", count: totals.ok, color: "bg-emerald-500", label: "OK" },
    { key: "changed", count: totals.changed, color: "bg-amber-500", label: "Changed" },
    { key: "failed", count: totals.failures, color: "bg-red-500", label: "Failed" },
    { key: "unreachable", count: totals.unreachable, color: "bg-orange-500", label: "Unreachable" },
    { key: "skipped", count: totals.skipped, color: "bg-zinc-600", label: "Skipped" },
  ].filter((s) => s.count > 0);

  return (
    <div className="space-y-2">
      {/* Stacked bar */}
      <div className="flex h-2 rounded-full overflow-hidden bg-zinc-800">
        {segments.map((seg) => (
          <div
            key={seg.key}
            className={cn("h-full transition-all", seg.color)}
            style={{ width: `${(seg.count / total) * 100}%` }}
            title={`${seg.label}: ${seg.count}`}
          />
        ))}
      </div>
      {/* Legend */}
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {segments.map((seg) => (
          <div key={seg.key} className="flex items-center gap-1.5 text-[11px]">
            <div className={cn("h-2 w-2 rounded-full", seg.color)} />
            <span className="text-zinc-400">{seg.label}</span>
            <span className="font-mono text-zinc-500">{seg.count}</span>
          </div>
        ))}
        <div className="flex items-center gap-1.5 text-[11px] ml-auto">
          <span className="text-zinc-500">Hosts:</span>
          <span className="font-mono text-zinc-400">{Object.keys(stats).length}</span>
        </div>
      </div>
      {/* Per-host detail */}
      <div className="space-y-1">
        {Object.entries(stats).map(([host, counts]) => (
          <div key={host} className="flex items-center gap-2 text-[10px] font-mono">
            <span className="text-zinc-500 w-32 truncate">{host}</span>
            <div className="flex gap-2">
              {counts.ok > 0 && <span className="text-emerald-400">ok={counts.ok}</span>}
              {counts.changed > 0 && <span className="text-amber-400">changed={counts.changed}</span>}
              {counts.failures > 0 && <span className="text-red-400">failed={counts.failures}</span>}
              {counts.unreachable > 0 && <span className="text-orange-400">unreachable={counts.unreachable}</span>}
              {counts.skipped > 0 && <span className="text-zinc-600">skip={counts.skipped}</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

type ViewMode = "structured" | "raw" | "logs";

function RunSection({
  run,
  isLatest,
  isStreaming,
}: {
  run: ExecutionRun;
  isLatest: boolean;
  isStreaming: boolean;
}) {
  const [expanded, setExpanded] = useState(isLatest);
  const [filters, setFilters] = useState<Set<StatusFilter>>(
    new Set(["ok", "changed", "failed", "skipped", "unreachable"])
  );
  const [showFilters, setShowFilters] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>("structured");

  const filteredTasks = run.tasks.filter((t) => {
    const mapped = STATUS_MAP[t.event];
    return mapped ? filters.has(mapped) : true;
  });

  const counts = useMemo(() => {
    const c = { ok: 0, changed: 0, failed: 0, skipped: 0, unreachable: 0 };
    for (const t of run.tasks) {
      const mapped = STATUS_MAP[t.event];
      if (mapped && mapped in c) c[mapped as keyof typeof c]++;
    }
    return c;
  }, [run.tasks]);

  const toggleFilter = (f: StatusFilter) => {
    setFilters((prev) => {
      const next = new Set(prev);
      if (next.has(f)) next.delete(f);
      else next.add(f);
      return next;
    });
  };

  const isRunActive = isLatest && isStreaming;
  const modePill = run.mode === "apply"
    ? "bg-zinc-700/30 text-zinc-300 border-zinc-600/40"
    : "bg-zinc-800 text-zinc-400 border-zinc-700";

  return (
    <div className="border-b border-zinc-800/50 last:border-b-0 min-w-0">
      {/* Run header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full min-w-0 px-4 py-3 text-left hover:bg-zinc-900/50 transition-colors"
      >
        {expanded
          ? <ChevronDown className="h-3.5 w-3.5 text-zinc-500 shrink-0" />
          : <ChevronRight className="h-3.5 w-3.5 text-zinc-500 shrink-0" />
        }
        <Play className="h-3 w-3 text-zinc-500 shrink-0" />
        <span className="text-xs font-medium text-zinc-300 truncate">
          {run.playbook || run.tool}
        </span>
        <span className={cn(
          "text-[10px] font-mono px-1.5 py-0.5 rounded border shrink-0",
          modePill
        )}>
          {run.mode}
        </span>
        {isRunActive && (
          <span className="flex items-center gap-1 text-[10px] text-zinc-400">
            <span className="h-1.5 w-1.5 rounded-full bg-zinc-400 animate-pulse-dot" />
            running
          </span>
        )}
        <span className="ml-auto text-[10px] font-mono text-zinc-600">
          {run.tasks.length} tasks
        </span>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-3 animate-slide-in min-w-0 overflow-hidden">
          {/* Toolbar: view mode toggle + filter */}
          <div className="flex flex-wrap items-center gap-2 min-w-0">
            <div className="flex items-center rounded-md border border-zinc-800 overflow-hidden shrink-0">
              <button
                onClick={() => setViewMode("structured")}
                className={cn(
                  "flex items-center gap-1 px-2 py-1 text-[10px] font-medium transition-colors",
                  viewMode === "structured"
                    ? "bg-zinc-800 text-zinc-200"
                    : "text-zinc-500 hover:text-zinc-300"
                )}
              >
                <Filter className="h-3 w-3" />
                Tasks
              </button>
              <button
                onClick={() => setViewMode("raw")}
                className={cn(
                  "flex items-center gap-1 px-2 py-1 text-[10px] font-medium transition-colors border-l border-zinc-800",
                  viewMode === "raw"
                    ? "bg-zinc-800 text-zinc-200"
                    : "text-zinc-500 hover:text-zinc-300",
                  !run.rawStdout && "opacity-40 cursor-not-allowed"
                )}
                disabled={!run.rawStdout}
                title={run.rawStdout ? "View raw Ansible output" : "Raw output not available"}
              >
                <Terminal className="h-3 w-3" />
                Raw
              </button>
              {run.detectedLogs && run.detectedLogs.length > 0 && (
                <button
                  onClick={() => setViewMode("logs")}
                  className={cn(
                    "flex items-center gap-1 px-2 py-1 text-[10px] font-medium transition-colors border-l border-zinc-800",
                    viewMode === "logs"
                      ? "bg-zinc-800 text-zinc-200"
                      : "text-zinc-500 hover:text-zinc-300"
                  )}
                  title="Log files detected during execution"
                >
                  <ScrollText className="h-3 w-3" />
                  Logs ({run.detectedLogs.length})
                </button>
              )}
            </div>

            {viewMode === "structured" && (
              <>
                <button
                  onClick={() => setShowFilters(!showFilters)}
                  className="flex items-center gap-1 text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors shrink-0"
                >
                  <Filter className="h-3 w-3" />
                  Filter
                </button>
                {showFilters && (
                  <div className="flex flex-wrap gap-1.5">
                    {(["ok", "changed", "failed", "skipped", "unreachable"] as StatusFilter[]).map(
                      (f) => (
                        <button
                          key={f}
                          onClick={() => toggleFilter(f)}
                          className={cn(
                            "text-[10px] px-1.5 py-0.5 rounded font-mono transition-colors",
                            filters.has(f)
                              ? f === "ok" ? "bg-emerald-500/20 text-emerald-400"
                                : f === "changed" ? "bg-amber-500/20 text-amber-400"
                                : f === "failed" ? "bg-red-500/20 text-red-400"
                                : f === "unreachable" ? "bg-orange-500/20 text-orange-400"
                                : "bg-zinc-700/50 text-zinc-400"
                              : "bg-zinc-900 text-zinc-600"
                          )}
                        >
                          {f} {counts[f]}
                        </button>
                      )
                    )}
                  </div>
                )}
              </>
            )}

            {isRunActive && (
              <span className="ml-auto text-[10px] font-mono text-zinc-500 animate-pulse">
                Task {run.tasks.length} executing...
              </span>
            )}
          </div>

          {viewMode === "structured" ? (
            <>
              {/* Task tree */}
              <div className="pl-1">
                {filteredTasks.map((task, i) => (
                  <TaskNode
                    key={i}
                    task={task}
                    isLast={i === filteredTasks.length - 1}
                    isActive={isRunActive && i === filteredTasks.length - 1}
                  />
                ))}
                {filteredTasks.length === 0 && (
                  <p className="text-[11px] text-zinc-600 py-2">No tasks match current filters</p>
                )}
              </div>

              {/* Recap bar */}
              {run.summary?.stats && (
                <div className="rounded-lg bg-zinc-900/50 border border-zinc-800 p-3">
                  <div className="text-[10px] text-zinc-500 uppercase tracking-wider font-medium mb-2">
                    Play Recap
                  </div>
                  <RecapBar stats={run.summary.stats} />
                </div>
              )}
            </>
          ) : viewMode === "logs" ? (
            <DetectedLogsView logs={run.detectedLogs || []} />
          ) : (
            <RawOutputView stdout={run.rawStdout || ""} />
          )}
        </div>
      )}
    </div>
  );
}

function DetectedLogsView({ logs }: { logs: DetectedLog[] }) {
  const [expandedLog, setExpandedLog] = useState<string | null>(
    logs.length === 1 ? logs[0].path : null,
  );

  if (logs.length === 0) {
    return (
      <div className="rounded-md bg-zinc-900/50 border border-zinc-800 px-4 py-6 text-center">
        <ScrollText className="h-5 w-5 text-zinc-600 mx-auto mb-2" />
        <p className="text-[11px] text-zinc-600">No log files detected</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {logs.map((log) => {
        const isOpen = expandedLog === log.path;
        const sizeKB = Math.round(parseInt(log.size, 10) / 1024);
        return (
          <div key={log.path} className="rounded-md border border-zinc-800 overflow-hidden">
            <button
              onClick={() => setExpandedLog(isOpen ? null : log.path)}
              className="flex items-center gap-2 w-full px-3 py-2 text-left hover:bg-zinc-900/50 transition-colors"
            >
              {isOpen
                ? <ChevronDown className="h-3 w-3 text-zinc-500 shrink-0" />
                : <ChevronRight className="h-3 w-3 text-zinc-500 shrink-0" />}
              <ScrollText className="h-3 w-3 text-amber-500 shrink-0" />
              <span className="text-xs font-mono text-zinc-300 truncate">{log.path}</span>
              <span className="ml-auto text-[10px] text-zinc-600 shrink-0">{sizeKB} KB</span>
            </button>
            {isOpen && (
              <pre className="p-3 text-[11px] font-mono bg-zinc-950 border-t border-zinc-800 overflow-x-auto overflow-y-auto max-h-[50vh] whitespace-pre-wrap text-zinc-400 leading-relaxed">
                {log.preview}
              </pre>
            )}
          </div>
        );
      })}
    </div>
  );
}

function RawOutputView({ stdout }: { stdout: string }) {
  if (!stdout) {
    return (
      <div className="rounded-md bg-zinc-900/50 border border-zinc-800 px-4 py-6 text-center">
        <Terminal className="h-5 w-5 text-zinc-600 mx-auto mb-2" />
        <p className="text-[11px] text-zinc-600">Raw output not available for this run</p>
      </div>
    );
  }

  return (
    <div className="rounded-md border border-zinc-800 overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-1.5 bg-zinc-900 border-b border-zinc-800">
        <Terminal className="h-3 w-3 text-zinc-500" />
        <span className="text-[10px] text-zinc-500 font-medium uppercase tracking-wider">
          ansible-playbook output
        </span>
      </div>
      <pre className="p-3 text-[11px] font-mono bg-zinc-950 overflow-x-auto overflow-y-auto max-h-[70vh] whitespace-pre leading-relaxed">
        {colorizeAnsibleOutput(stdout)}
      </pre>
    </div>
  );
}

function colorizeAnsibleOutput(text: string): React.ReactNode {
  return text.split("\n").map((line, i) => {
    let className = "text-zinc-400";

    if (/^PLAY \[/.test(line)) {
      className = "text-zinc-200 font-bold";
    } else if (/^TASK \[/.test(line)) {
      className = "text-zinc-300 font-medium";
    } else if (/^PLAY RECAP/.test(line)) {
      className = "text-zinc-200 font-bold";
    } else if (/^ok:/.test(line)) {
      className = "text-emerald-400";
    } else if (/^changed:/.test(line)) {
      className = "text-amber-400";
    } else if (/^fatal:/.test(line) || /^FAILED/.test(line)) {
      className = "text-red-400";
    } else if (/^skipping:/.test(line)) {
      className = "text-zinc-600";
    } else if (/unreachable=\d+/.test(line) || /failed=\d+/.test(line)) {
      const hasFailures = /failed=[1-9]/.test(line) || /unreachable=[1-9]/.test(line);
      className = hasFailures ? "text-red-400" : "text-emerald-400";
    } else if (line.startsWith("---") || line.startsWith("+++")) {
      className = "text-zinc-500";
    } else if (line.startsWith("+")) {
      className = "text-emerald-400/80";
    } else if (line.startsWith("-") && !line.startsWith("---")) {
      className = "text-red-400/80";
    } else if (line.startsWith("*")) {
      className = "text-zinc-500";
    }

    return (
      <div key={i} className={className}>{line || "\u00A0"}</div>
    );
  });
}

const FRIENDLY_TOOL_NAMES: Record<string, string> = {
  write_file: "Write file",
  generate_playbook: "Generate playbook",
  scaffold_role: "Scaffold role",
  execute_playbook: "Execute playbook",
  run_adhoc: "Ad-hoc command",
  local_exec: "Local command",
  test_connectivity: "Test connectivity",
  collect_facts: "Collect facts",
  manage_inventory: "Manage inventory",
  read_file: "Read file",
  render_template: "Render template",
  manage_git: "Git",
  verify_state: "Verify state",
  manage_galaxy: "Galaxy",
  search_docs: "Search docs",
  run_lint: "Lint",
  manage_vault: "Vault",
  import_project: "Import project",
  terraform_exec: "Terraform",
  generate_terraform: "Generate Terraform",
  web_search: "Web search",
  request_secret: "Request secret",
};

interface ToolActivity {
  id: string;
  tool: string;
  label: string;
  status: string;
  timestamp: number;
  output?: string;
  isAnsibleRun: boolean;
}

function extractToolActivity(events: AgentEvent[]): ToolActivity[] {
  const callArgs = new Map<string, Record<string, unknown>>();
  for (const ev of events) {
    if (ev.event !== "tool_call") continue;
    const callId = (ev.data.tool_call_id as string) || "";
    const args = ev.data.arguments as Record<string, unknown> | undefined;
    if (callId && args) callArgs.set(callId, args);
  }

  const activities: ToolActivity[] = [];
  for (const ev of events) {
    if (ev.event !== "tool_result") continue;
    const tool = (ev.data.tool as string) || "";
    if (!tool) continue;
    const status = (ev.data.status as string) || "success";
    const data = ev.data.data as Record<string, unknown> | undefined;
    const output = (ev.data.output as string) || "";
    const callId = (ev.data.tool_call_id as string) || "";
    const args = callArgs.get(callId);

    let label = FRIENDLY_TOOL_NAMES[tool] || tool.replace(/_/g, " ");
    let isAnsibleRun = false;

    if (tool === "execute_playbook" && data) {
      const playbook = (data.playbook as string) || "";
      const mode = (data.mode as string) || "check";
      label = playbook ? `${playbook} (${mode})` : `Playbook (${mode})`;
      isAnsibleRun = true;
    } else if (tool === "run_adhoc" && data) {
      const module = (data.module_args as string) || (data.module as string) || "command";
      label = module.length > 50 ? `adhoc: ${module.slice(0, 47)}...` : `adhoc: ${module}`;
      isAnsibleRun = true;
    } else if (tool === "local_exec") {
      const cmd = (args?.command as string) || "";
      if (cmd) {
        label = cmd.length > 60 ? cmd.slice(0, 57) + "..." : cmd;
      } else {
        label = output.length > 60 ? output.slice(0, 57) + "..." : output || "Local command";
      }
    } else if (tool === "write_file") {
      const path = (args?.path as string) || (data?.path as string) || "";
      label = path ? `Write ${path.split("/").pop()}` : "Write file";
    } else if (tool === "scaffold_role") {
      const roleName = (args?.role_name as string) || (data?.role_name as string) || "";
      label = roleName ? `Scaffold role: ${roleName}` : "Scaffold role";
    } else if (tool === "generate_playbook") {
      const path = (args?.path as string) || (data?.path as string) || "";
      label = path ? `Generate ${path.split("/").pop()}` : "Generate playbook";
    } else if (tool === "test_connectivity") {
      const hosts = (args?.hosts as string) || "";
      label = hosts ? `Test ${hosts}` : "Test connectivity";
    }

    activities.push({
      id: ev.id,
      tool,
      label,
      status,
      timestamp: ev.timestamp,
      output: output.length > 200 ? output.slice(0, 197) + "..." : output,
      isAnsibleRun,
    });
  }
  return activities;
}

function ToolActivityEntry({ activity }: { activity: ToolActivity }) {
  const isError = activity.status === "error" || activity.status === "failed";
  const isApproval = activity.status === "needs_approval";

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-zinc-900/50 transition-colors">
      {isError ? (
        <XCircle className="h-3 w-3 text-red-400 shrink-0" />
      ) : isApproval ? (
        <Clock className="h-3 w-3 text-amber-400 shrink-0" />
      ) : activity.isAnsibleRun ? (
        <Play className="h-3 w-3 text-emerald-400 shrink-0" />
      ) : activity.tool === "write_file" || activity.tool === "generate_playbook" || activity.tool === "scaffold_role" ? (
        <FileCode2 className="h-3 w-3 text-blue-400 shrink-0" />
      ) : (
        <Wrench className="h-3 w-3 text-zinc-500 shrink-0" />
      )}
      <span className={cn(
        "flex-1 truncate font-mono",
        isError ? "text-red-300" : "text-zinc-300"
      )}>
        {activity.label}
      </span>
      <span className="text-[10px] font-mono text-zinc-600 shrink-0">
        {new Date(activity.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
      </span>
    </div>
  );
}

function ToolActivityLog({ events, hasAnsibleRuns }: { events: AgentEvent[]; hasAnsibleRuns: boolean }) {
  const allActivities = useMemo(() => extractToolActivity(events), [events]);
  const activities = hasAnsibleRuns
    ? allActivities.filter((a) => !a.isAnsibleRun)
    : allActivities;

  if (activities.length === 0) return null;

  const errorCount = activities.filter((a) => a.status === "error" || a.status === "failed").length;

  return (
    <div className={hasAnsibleRuns ? "border-t border-zinc-800" : ""}>
      <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-800/50">
        <Wrench className="h-3 w-3 text-zinc-500" />
        <span className="text-[10px] text-zinc-500 uppercase tracking-wider font-medium">
          Tool Activity
        </span>
        <span className="text-[10px] font-mono text-zinc-600">
          {activities.length} call{activities.length !== 1 ? "s" : ""}
          {errorCount > 0 && <span className="text-red-400 ml-1">· {errorCount} failed</span>}
        </span>
      </div>
      <div className={cn(
        "divide-y divide-zinc-800/30 overflow-y-auto",
        hasAnsibleRuns && "max-h-[50vh]"
      )}>
        {activities.map((a) => (
          <ToolActivityEntry key={a.id} activity={a} />
        ))}
      </div>
    </div>
  );
}

interface ExecutionTimelineProps {
  events: AgentEvent[];
  isStreaming: boolean;
  playbooks: Record<string, string>;
  inventory: Record<string, string>;
}

function LiveTaskIcon({ type }: { type: string }) {
  switch (type) {
    case "task_ok":
      return <CheckCircle2 className="h-3 w-3 text-emerald-500 shrink-0" />;
    case "task_failed":
    case "host_unreachable":
      return <XCircle className="h-3 w-3 text-red-400 shrink-0" />;
    case "task_skipped":
      return <MinusCircle className="h-3 w-3 text-zinc-600 shrink-0" />;
    case "task_start":
      return <Circle className="h-3 w-3 text-blue-400 shrink-0 animate-pulse" />;
    case "play_start":
      return <Play className="h-3 w-3 text-blue-400 shrink-0" />;
    default:
      return <Circle className="h-3 w-3 text-zinc-600 shrink-0" />;
  }
}

function formatLiveTask(data: Record<string, unknown>): string {
  const type = data.type as string;
  const task = (data.task as string) || "";
  const host = (data.host as string) || "";
  const changed = data.changed as boolean;

  if (type === "play_start") return (data.play as string) || "Play starting";
  if (type === "task_start") return task || "Starting task";
  if (type === "task_ok") {
    const label = changed ? "changed" : "ok";
    return host ? `${task} (${host}) — ${label}` : `${task} — ${label}`;
  }
  if (type === "task_failed") {
    const err = (data.error as string) || "failed";
    const short = err.length > 60 ? err.slice(0, 57) + "..." : err;
    return host ? `${task} (${host}) FAILED: ${short}` : `${task}: ${short}`;
  }
  if (type === "task_skipped") return host ? `${task} (${host}) — skipped` : `${task} — skipped`;
  if (type === "host_unreachable") return `${host || "host"} — unreachable`;
  if (type === "stats") return "Playbook complete";
  return task || "...";
}

const _LONG_RUN_TOOLS = new Set(["execute_playbook", "run_adhoc", "local_exec", "terraform_exec"]);

type LiveTab = "all" | "output" | "ansible";

function isOutputEvent(ev: AgentEvent): boolean {
  return ev.data.source === "log_file"
    || (ev.data.type as string) === "shell_output"
    || (ev.data.type as string) === "stderr_line";
}

function isAnsibleEvent(ev: AgentEvent): boolean {
  return !ev.data.source
    && (ev.data.type as string) !== "shell_output"
    && (ev.data.type as string) !== "stderr_line";
}

function LiveRunSection({ events }: { events: AgentEvent[] }) {
  const [tab, setTab] = useState<LiveTab>("all");
  const scrollRef = useRef<HTMLDivElement>(null);
  const userScrolledUp = useRef(false);

  const liveLogs = useMemo(
    () => events.filter((e) => e.event === "live_log"),
    [events]
  );

  const lastToolCall = useMemo(() => {
    const calls = events.filter(
      (e) => e.event === "tool_call" && _LONG_RUN_TOOLS.has(e.data.tool as string)
    );
    return calls[calls.length - 1];
  }, [events]);

  const lastToolResult = useMemo(() => {
    const results = events.filter(
      (e) => e.event === "tool_result" && _LONG_RUN_TOOLS.has(e.data.tool as string)
    );
    return results[results.length - 1];
  }, [events]);

  const isRunning = lastToolCall && (!lastToolResult || lastToolCall.timestamp > lastToolResult.timestamp);

  const filtered = useMemo(() => {
    const recent = liveLogs.slice(-80);
    if (tab === "output") return recent.filter(isOutputEvent);
    if (tab === "ansible") return recent.filter(isAnsibleEvent);
    return recent;
  }, [liveLogs, tab]);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
    userScrolledUp.current = !atBottom;
  }, []);

  useEffect(() => {
    if (!userScrolledUp.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [filtered]);

  if (!isRunning || liveLogs.length === 0) return null;

  const args = lastToolCall.data.arguments as Record<string, unknown> | undefined;
  const playbook = (args?.playbook as string) || (args?.command as string)?.slice(0, 40) || (lastToolCall.data.tool as string) || "command";

  const okCount = liveLogs.filter((e) => (e.data.type as string) === "task_ok").length;
  const failedCount = liveLogs.filter((e) => (e.data.type as string) === "task_failed").length;
  const changedCount = liveLogs.filter((e) => e.data.changed === true).length;
  const hasCounters = okCount > 0 || failedCount > 0;

  const outputCount = liveLogs.filter(isOutputEvent).length;
  const ansibleCount = liveLogs.filter(isAnsibleEvent).length;

  return (
    <div className="border-b border-zinc-800/50">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 bg-blue-950/20 border-b border-blue-900/20">
        <Loader2 className="h-3.5 w-3.5 text-blue-400 animate-spin shrink-0" />
        <span className="text-xs font-medium text-blue-300 truncate">{playbook}</span>
        {hasCounters && (
          <span className="text-[10px] text-zinc-500 ml-auto whitespace-nowrap">
            {okCount > 0 && <span className="text-emerald-600">{okCount} ok</span>}
            {changedCount > 0 && <span className="text-amber-600 ml-1.5">{changedCount} chg</span>}
            {failedCount > 0 && <span className="text-red-400 ml-1.5">{failedCount} fail</span>}
          </span>
        )}
        {!hasCounters && (
          <span className="text-[10px] text-blue-400/60 ml-auto whitespace-nowrap">running</span>
        )}
      </div>

      {/* Tab bar */}
      <div className="flex border-b border-zinc-800/40 bg-zinc-950/40">
        {([
          ["all", "All", liveLogs.length],
          ["output", "Output", outputCount],
          ["ansible", "Ansible", ansibleCount],
        ] as [LiveTab, string, number][]).map(([id, label, count]) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={cn(
              "flex-1 px-2 py-1.5 text-[10px] transition-colors",
              tab === id
                ? "text-blue-300 border-b border-blue-400"
                : "text-zinc-500 hover:text-zinc-400",
            )}
          >
            {label}{count > 0 ? ` (${count})` : ""}
          </button>
        ))}
      </div>

      {/* Log content */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="max-h-72 overflow-y-auto"
      >
        <DedupedLogList events={filtered} />
        {filtered.length === 0 && (
          <div className="px-3 py-4 text-[11px] text-zinc-600 text-center">
            No {tab === "all" ? "" : tab + " "}events yet
          </div>
        )}
      </div>
    </div>
  );
}

function LogFileBlock({ ev }: { ev: AgentEvent }) {
  const file = (ev.data.file as string) || "log";
  const content = (ev.data.content as string) || "";
  const lines = content.split("\n").filter(Boolean);

  return (
    <div className="border-l-2 border-cyan-800/40">
      <div className="px-3 py-0.5 text-[9px] text-zinc-500 bg-zinc-950/50 truncate">
        {file}
      </div>
      {lines.map((ln, i) => (
        <div key={`${ev.id}-${i}`} className="px-3 py-0 text-[11px] font-mono text-cyan-300/80 whitespace-pre-wrap break-all">
          {ln}
        </div>
      ))}
    </div>
  );
}

function AnsibleEventRow({ ev, count }: { ev: AgentEvent; count?: number }) {
  const type = ev.data.type as string;
  const isFailed = type === "task_failed" || type === "host_unreachable";

  return (
    <div className={cn(
      "flex items-center gap-2 px-3 py-1 text-[11px] hover:bg-zinc-900/30",
      isFailed && "border-l-2 border-red-500/60 bg-red-950/10",
    )}>
      <LiveTaskIcon type={type} />
      <span className={cn(
        "truncate",
        isFailed ? "text-red-400"
          : type === "task_skipped" ? "text-zinc-600"
          : type === "play_start" || type === "task_start" ? "text-blue-400"
          : "text-zinc-400"
      )}>
        {formatLiveTask(ev.data)}
      </span>
      {count && count > 1 && (
        <span className="text-[9px] text-zinc-600 shrink-0 ml-auto">×{count}</span>
      )}
    </div>
  );
}

function DedupedLogList({ events }: { events: AgentEvent[] }) {
  type RenderItem =
    | { kind: "output"; ev: AgentEvent }
    | { kind: "log_file"; ev: AgentEvent }
    | { kind: "ansible"; ev: AgentEvent; count: number };

  const items = useMemo(() => {
    const result: RenderItem[] = [];
    for (const ev of events) {
      if (ev.data.source === "log_file") {
        result.push({ kind: "log_file", ev });
        continue;
      }
      const type = ev.data.type as string;
      if (type === "shell_output" || type === "stderr_line") {
        result.push({ kind: "output", ev });
        continue;
      }
      const prev = result[result.length - 1];
      if (
        prev?.kind === "ansible" &&
        (type === "task_ok" || type === "task_skipped") &&
        (prev.ev.data.type as string) === type &&
        (prev.ev.data.task as string) === (ev.data.task as string)
      ) {
        prev.count++;
        prev.ev = ev;
      } else {
        result.push({ kind: "ansible", ev, count: 1 });
      }
    }
    return result;
  }, [events]);

  return (
    <>
      {items.map((item) => {
        if (item.kind === "log_file") {
          return <LogFileBlock key={item.ev.id} ev={item.ev} />;
        }
        if (item.kind === "output") {
          const type = item.ev.data.type as string;
          return (
            <div
              key={item.ev.id}
              className={cn(
                "px-3 py-0.5 text-[11px] font-mono",
                type === "stderr_line" ? "text-amber-400/80" : "text-cyan-300/80",
              )}
            >
              {(item.ev.data.line as string) || ""}
            </div>
          );
        }
        return (
          <AnsibleEventRow
            key={item.ev.id}
            ev={item.ev}
            count={item.count}
          />
        );
      })}
    </>
  );
}

export function ExecutionTimeline({
  events,
  isStreaming,
  playbooks,
  inventory,
}: ExecutionTimelineProps) {
  const runs = useMemo(() => extractRuns(events), [events]);
  const toolResultCount = useMemo(
    () => events.filter((e) => e.event === "tool_result").length,
    [events]
  );
  const hasLiveLogs = useMemo(
    () => events.some((e) => e.event === "live_log"),
    [events]
  );

  if (runs.length === 0 && toolResultCount === 0 && !hasLiveLogs) {
    const pbCount = Object.keys(playbooks).length;
    const invCount = Object.keys(inventory).length;
    const hasArtifacts = pbCount > 0 || invCount > 0;

    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 p-6 text-center">
        <div className="rounded-xl bg-zinc-900/50 p-4 ring-1 ring-zinc-800">
          <ScrollText className="h-8 w-8 text-zinc-600" />
        </div>
        <div>
          <p className="text-xs text-zinc-500">No execution logs yet</p>
          <p className="mt-1 text-[11px] text-zinc-600">
            Tool calls and playbook runs will appear here
          </p>
        </div>
        {hasArtifacts && (
          <div className="flex gap-3 text-[10px] text-zinc-600">
            {pbCount > 0 && <span>{pbCount} playbook{pbCount > 1 ? "s" : ""} generated</span>}
            {invCount > 0 && <span>{invCount} inventory file{invCount > 1 ? "s" : ""}</span>}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="min-w-0 w-full">
      {isStreaming && <LiveRunSection events={events} />}
      {runs.length > 0 && (
        <div className="divide-y divide-zinc-800/50">
          {runs.map((run, i) => (
            <RunSection
              key={run.id}
              run={run}
              isLatest={i === runs.length - 1}
              isStreaming={isStreaming}
            />
          ))}
        </div>
      )}
      <ToolActivityLog events={events} hasAnsibleRuns={runs.length > 0} />
    </div>
  );
}
