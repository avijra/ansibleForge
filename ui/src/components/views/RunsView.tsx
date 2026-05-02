import { useCallback, useEffect, useState } from "react";
import { GitBranch, RefreshCw, CheckCircle2, XCircle, Play, Eye } from "lucide-react";
import { request } from "@/api/client";
import { cn } from "@/lib/utils";

interface RunData {
  id: number;
  session_id: string;
  playbook: string;
  mode: string;
  hosts: string[];
  status: string;
  event_count: number;
  started_at: number;
  finished_at: number | null;
}

function statusIcon(status: string) {
  switch (status) {
    case "success":
      return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />;
    case "failed":
      return <XCircle className="h-3.5 w-3.5 text-red-400" />;
    default:
      return <Play className="h-3.5 w-3.5 text-zinc-500" />;
  }
}

function modeLabel(mode: string) {
  return mode === "check" ? "dry-run" : mode;
}

function timeAgo(ts: number): string {
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function RunsView() {
  const [runs, setRuns] = useState<RunData[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await request<RunData[]>("/infrastructure/runs?limit=100");
      setRuns(data);
    } catch {
      // API may not be available
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
        <div className="flex items-center gap-2">
          <GitBranch className="h-4 w-4 text-zinc-400" />
          <h2 className="text-sm font-semibold text-zinc-200">Run History</h2>
          <span className="text-[10px] text-zinc-600">{runs.length} run{runs.length !== 1 ? "s" : ""}</span>
        </div>
        <button
          onClick={refresh}
          disabled={loading}
          className="rounded-md p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300 transition-colors"
          title="Refresh"
        >
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {runs.length === 0 && !loading ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-8">
            <GitBranch className="h-10 w-10 text-zinc-800 mb-3" />
            <p className="text-sm text-zinc-500">No runs recorded yet</p>
            <p className="text-xs text-zinc-700 mt-1">
              Execute a playbook and it will appear here.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-zinc-800/50">
            {runs.map((run) => (
              <div key={run.id} className="px-4 py-3 hover:bg-zinc-900/50 transition-colors">
                <div className="flex items-center gap-2.5">
                  {statusIcon(run.status)}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-zinc-200 truncate">
                        {run.playbook}
                      </span>
                      <span className={cn(
                        "rounded px-1.5 py-0.5 text-[10px] font-mono",
                        run.mode === "check"
                          ? "bg-blue-950/30 text-blue-400"
                          : "bg-emerald-950/30 text-emerald-400"
                      )}>
                        {modeLabel(run.mode)}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 mt-0.5 text-[10px] text-zinc-600">
                      <span>{run.hosts.slice(0, 3).join(", ")}{run.hosts.length > 3 ? ` +${run.hosts.length - 3}` : ""}</span>
                      <span>·</span>
                      <span>{run.event_count} events</span>
                      <span>·</span>
                      <span>{timeAgo(run.started_at)}</span>
                    </div>
                  </div>
                  <Eye className="h-3.5 w-3.5 text-zinc-700" />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
