import { useMemo } from "react";
import { Server, Wifi, WifiOff, HardDrive } from "lucide-react";
import type { AgentEvent } from "@/api/types";
import { cn } from "@/lib/utils";

interface HostInfo {
  name: string;
  lastSeen: number;
  reachable: boolean;
  os?: string;
  taskCount: number;
  failCount: number;
  changeCount: number;
}

function extractHosts(events: AgentEvent[]): HostInfo[] {
  const hostMap = new Map<string, HostInfo>();

  for (const ev of events) {
    if (ev.event !== "tool_result") continue;
    const data = ev.data.data as Record<string, unknown> | undefined;
    const tasks = (data?.events as Array<{ event: string; host: string; task: string; result?: Record<string, unknown> }>) || [];

    for (const task of tasks) {
      if (!task.host) continue;
      const existing = hostMap.get(task.host) || {
        name: task.host,
        lastSeen: ev.timestamp,
        reachable: true,
        taskCount: 0,
        failCount: 0,
        changeCount: 0,
      };

      existing.taskCount++;
      existing.lastSeen = Math.max(existing.lastSeen, ev.timestamp);

      if (task.event === "runner_on_failed") existing.failCount++;
      if (task.event === "runner_on_changed") existing.changeCount++;
      if (task.event === "runner_on_unreachable") existing.reachable = false;
      if (task.event === "runner_on_ok" || task.event === "runner_on_changed") existing.reachable = true;

      if (task.task?.toLowerCase().includes("gathering facts") && task.result) {
        const facts = task.result.ansible_facts as Record<string, unknown> | undefined;
        if (facts?.ansible_distribution) {
          existing.os = `${facts.ansible_distribution} ${facts.ansible_distribution_version || ""}`.trim();
        }
      }

      hostMap.set(task.host, existing);
    }

    const summary = data?.summary as { stats?: Record<string, Record<string, number>> } | undefined;
    if (summary?.stats) {
      for (const host of Object.keys(summary.stats)) {
        if (!hostMap.has(host)) {
          hostMap.set(host, {
            name: host,
            lastSeen: ev.timestamp,
            reachable: true,
            taskCount: 0,
            failCount: 0,
            changeCount: 0,
          });
        }
      }
    }
  }

  return Array.from(hostMap.values()).sort((a, b) => b.lastSeen - a.lastSeen);
}

function timeAgo(ts: number): string {
  const diff = Date.now() - ts;
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function HostCard({ host }: { host: HostInfo }) {
  const healthColor = host.failCount > 0
    ? "border-red-800/40"
    : host.changeCount > 0
      ? "border-amber-800/40"
      : "border-zinc-800";

  return (
    <div className={cn(
      "rounded-lg border bg-zinc-900/50 p-3 space-y-2 transition-colors hover:bg-zinc-900/80",
      healthColor
    )}>
      <div className="flex items-center gap-2">
        <Server className="h-4 w-4 text-zinc-500 shrink-0" />
        <span className="text-xs font-mono text-zinc-200 font-medium truncate flex-1">
          {host.name}
        </span>
        {host.reachable ? (
          <Wifi className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
        ) : (
          <WifiOff className="h-3.5 w-3.5 text-red-400 shrink-0" />
        )}
      </div>

      {host.os && (
        <div className="flex items-center gap-1.5 text-[10px] text-zinc-500">
          <HardDrive className="h-3 w-3" />
          {host.os}
        </div>
      )}

      <div className="flex items-center gap-3 text-[10px] font-mono">
        <span className="text-zinc-500">{host.taskCount} tasks</span>
        {host.changeCount > 0 && <span className="text-amber-400">{host.changeCount} changed</span>}
        {host.failCount > 0 && <span className="text-red-400">{host.failCount} failed</span>}
        <span className="ml-auto text-zinc-600">{timeAgo(host.lastSeen)}</span>
      </div>
    </div>
  );
}

export function HostInventory({ events }: { events: AgentEvent[] }) {
  const hosts = useMemo(() => extractHosts(events), [events]);

  if (hosts.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 p-6 text-center">
        <div className="rounded-xl bg-zinc-900/50 p-4 ring-1 ring-zinc-800">
          <Server className="h-8 w-8 text-zinc-600" />
        </div>
        <div>
          <p className="text-xs text-zinc-500">No hosts discovered</p>
          <p className="mt-1 text-[11px] text-zinc-600">
            Hosts will appear here after running playbooks or collecting facts
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-3 space-y-2">
      <div className="flex items-center justify-between px-1 mb-1">
        <span className="text-[10px] text-zinc-500 uppercase tracking-wider font-medium">
          {hosts.length} host{hosts.length !== 1 ? "s" : ""} discovered
        </span>
        <span className="text-[10px] text-zinc-600">
          {hosts.filter((h) => h.reachable).length} reachable
        </span>
      </div>
      {hosts.map((host) => (
        <HostCard key={host.name} host={host} />
      ))}
    </div>
  );
}
