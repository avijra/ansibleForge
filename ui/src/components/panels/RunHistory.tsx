import { useMemo } from "react";
import { CheckCircle2, XCircle, GitBranch, Clock } from "lucide-react";
import type { AgentEvent } from "@/api/types";
import { cn } from "@/lib/utils";

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
}

function extractRunHistory(events: AgentEvent[]): RunRecord[] {
  const records: RunRecord[] = [];

  for (const ev of events) {
    if (ev.event !== "tool_result") continue;
    const data = ev.data.data as Record<string, unknown> | undefined;
    const tasks = (data?.events as Array<{ event: string }>) || [];
    if (tasks.length === 0) continue;

    const summary = data?.summary as { stats?: Record<string, Record<string, number>> } | undefined;
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
      playbook: (data?.playbook as string) || (ev.data.tool as string) || "playbook",
      mode: (data?.mode as string) || "check",
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
  const runs = useMemo(() => extractRunHistory(events), [events]);

  if (runs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 p-6 text-center">
        <div className="rounded-xl bg-zinc-900/50 p-4 ring-1 ring-zinc-800">
          <GitBranch className="h-8 w-8 text-zinc-600" />
        </div>
        <div>
          <p className="text-xs text-zinc-500">No runs recorded</p>
          <p className="mt-1 text-[11px] text-zinc-600">
            Execution history will appear here
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-2">
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
                {run.failed > 0 ? (
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
