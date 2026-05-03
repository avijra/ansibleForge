import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Clock, GitBranch, RefreshCw, XCircle } from "lucide-react";
import type { AgentEvent } from "@/api/types";
import { request } from "@/api/client";
import { cn } from "@/lib/utils";

interface PersistedRun {
  id: number;
  session_id: string;
  playbook: string;
  mode: string;
  hosts: string[];
  status: string;
  event_count: number;
  summary: Record<string, Record<string, number>>;
  started_at: number;
  finished_at: number | null;
}

interface RunRecord {
  id: string;
  playbook: string;
  mode: string;
  status: string;
  taskCount: number;
  timestamp: number;
  ok: number;
  changed: number;
  failed: number;
  hosts?: string[];
}

function extractSessionRuns(events: AgentEvent[]): RunRecord[] {
  const records: RunRecord[] = [];

  for (const ev of events) {
    if (ev.event !== "tool_result") continue;
    const tool = (ev.data.tool as string) || "";
    const data = ev.data.data as Record<string, unknown> | undefined;
    if (!data) continue;

    if (tool === "run_adhoc") {
      const hostResults = data.host_results as Record<string, Record<string, unknown>> | undefined;
      if (!hostResults || Object.keys(hostResults).length === 0) continue;
      const moduleArgs = (data.module_args as string) || (data.module as string) || "command";
      const label = moduleArgs.length > 60 ? moduleArgs.slice(0, 60) + "..." : moduleArgs;
      let ok = 0, failed = 0;
      for (const r of Object.values(hostResults)) {
        if (r.status === "ok") ok++;
        else failed++;
      }
      records.push({
        id: ev.id,
        playbook: `adhoc: ${label}`,
        mode: "adhoc",
        status: (ev.data.status as string) || "success",
        taskCount: 1,
        timestamp: ev.timestamp,
        ok,
        changed: 0,
        failed,
        hosts: Object.keys(hostResults),
      });
      continue;
    }

    const tasks = (data.events as Array<{ event: string }>) || [];
    if (tasks.length === 0) continue;

    const summary = data.summary as { stats?: Record<string, Record<string, number>> } | undefined;
    let ok = 0, changed = 0, failed = 0;
    if (summary?.stats) {
      for (const counts of Object.values(summary.stats)) {
        ok += counts.ok || 0;
        changed += counts.changed || 0;
        failed += counts.failures || 0;
      }
    }

    records.push({
      id: ev.id,
      playbook: (data.playbook as string) || tool || "playbook",
      mode: (data.mode as string) || "check",
      status: (ev.data.status as string) || "success",
      taskCount: tasks.length,
      timestamp: ev.timestamp,
      ok,
      changed,
      failed,
    });
  }

  return records.reverse();
}

function persistedToRecords(runs: PersistedRun[]): RunRecord[] {
  return runs.map((r) => {
    let ok = 0, changed = 0, failed = 0;
    const stats = r.summary as unknown as Record<string, Record<string, number>> | undefined;
    if (stats) {
      for (const counts of Object.values(stats)) {
        if (typeof counts !== "object") continue;
        ok += counts.ok || 0;
        changed += counts.changed || 0;
        failed += counts.failures || 0;
      }
    }
    return {
      id: `run-${r.id}`,
      playbook: r.playbook,
      mode: r.mode,
      status: r.status,
      taskCount: r.event_count,
      timestamp: r.started_at * 1000,
      ok,
      changed,
      failed,
      hosts: r.hosts,
    };
  });
}

function mergeRuns(persisted: RunRecord[], session: RunRecord[]): RunRecord[] {
  const seen = new Set<string>();
  const merged: RunRecord[] = [];

  for (const r of session) {
    const key = `${r.playbook}:${r.mode}:${r.timestamp}`;
    seen.add(key);
    merged.push(r);
  }

  for (const r of persisted) {
    const key = `${r.playbook}:${r.mode}:${r.timestamp}`;
    if (!seen.has(key)) {
      merged.push(r);
    }
  }

  return merged.sort((a, b) => b.timestamp - a.timestamp);
}

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function MiniBar({ ok, changed, failed }: { ok: number; changed: number; failed: number }) {
  const total = ok + changed + failed;
  if (total === 0) return null;
  return (
    <div className="flex h-1.5 w-16 rounded-full overflow-hidden bg-zinc-800">
      {ok > 0 && (
        <div className="bg-emerald-500 h-full" style={{ width: `${(ok / total) * 100}%` }} />
      )}
      {changed > 0 && (
        <div className="bg-amber-500 h-full" style={{ width: `${(changed / total) * 100}%` }} />
      )}
      {failed > 0 && (
        <div className="bg-red-500 h-full" style={{ width: `${(failed / total) * 100}%` }} />
      )}
    </div>
  );
}

export function RunHistory({ events }: { events: AgentEvent[] }) {
  const [persistedRuns, setPersistedRuns] = useState<RunRecord[]>([]);
  const [loading, setLoading] = useState(true);

  const loadPersisted = useCallback(async () => {
    try {
      const data = await request<PersistedRun[]>("/infrastructure/runs");
      setPersistedRuns(persistedToRecords(data));
    } catch {
      // API may not be ready
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadPersisted(); }, [loadPersisted]);

  const sessionRuns = useMemo(() => extractSessionRuns(events), [events]);
  const runs = useMemo(() => mergeRuns(persistedRuns, sessionRuns), [persistedRuns, sessionRuns]);

  const toolResultCount = useMemo(
    () => events.filter((e) => e.event === "tool_result").length,
    [events]
  );

  if (runs.length === 0 && !loading) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 p-6 text-center">
        <div className="rounded-xl bg-zinc-900/50 p-4 ring-1 ring-zinc-800">
          <GitBranch className="h-8 w-8 text-zinc-600" />
        </div>
        <div>
          <p className="text-xs text-zinc-500">No playbook or adhoc runs yet</p>
          <p className="mt-1 text-[11px] text-zinc-600">
            {toolResultCount > 0
              ? `${toolResultCount} tool call${toolResultCount !== 1 ? "s" : ""} completed — check the Logs tab for details`
              : "Ansible playbook executions, adhoc commands, and Terraform runs appear here"}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-2">
      <div className="flex items-center justify-between px-2 mb-1">
        <span className="text-[10px] text-zinc-500 uppercase tracking-wider font-medium">
          {runs.length} run{runs.length !== 1 ? "s" : ""}
        </span>
        <button
          onClick={loadPersisted}
          className="rounded p-0.5 text-zinc-600 hover:text-zinc-400 transition-colors"
          title="Refresh"
        >
          <RefreshCw className="h-3 w-3" />
        </button>
      </div>
      <table className="w-full text-[11px]">
        <thead>
          <tr className="text-[10px] text-zinc-500 uppercase tracking-wider">
            <th className="text-left py-2 px-2 font-medium">Status</th>
            <th className="text-left py-2 px-2 font-medium">Playbook</th>
            <th className="text-left py-2 px-2 font-medium">Mode</th>
            <th className="text-left py-2 px-2 font-medium">Tasks</th>
            <th className="text-left py-2 px-2 font-medium">Result</th>
            <th className="text-right py-2 px-2 font-medium">Time</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/50">
          {runs.map((run) => (
            <tr
              key={run.id}
              className="hover:bg-zinc-900/50 transition-colors"
            >
              <td className="py-2 px-2">
                {run.failed > 0 || run.status === "failed" ? (
                  <XCircle className="h-3.5 w-3.5 text-red-400" />
                ) : (
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                )}
              </td>
              <td className="py-2 px-2 font-mono text-zinc-300 truncate max-w-[120px]">
                {run.playbook}
              </td>
              <td className="py-2 px-2">
                <span className={cn(
                  "font-mono px-1 py-0.5 rounded text-[10px]",
                  run.mode === "apply"
                    ? "bg-zinc-700/30 text-zinc-300"
                    : "bg-zinc-800 text-zinc-500"
                )}>
                  {run.mode}
                </span>
              </td>
              <td className="py-2 px-2 font-mono text-zinc-500">{run.taskCount}</td>
              <td className="py-2 px-2">
                <MiniBar ok={run.ok} changed={run.changed} failed={run.failed} />
              </td>
              <td className="py-2 px-2 text-right font-mono text-zinc-600 whitespace-nowrap">
                <Clock className="h-3 w-3 inline mr-1 -mt-px" />
                {formatTime(run.timestamp)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
