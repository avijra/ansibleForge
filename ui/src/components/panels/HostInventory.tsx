import { useCallback, useEffect, useMemo, useState } from "react";
import { HardDrive, RefreshCw, Server, Wifi, WifiOff } from "lucide-react";
import type { AgentEvent } from "@/api/types";
import { request } from "@/api/client";
import { cn } from "@/lib/utils";

interface PersistedHost {
  host_id: string;
  hostname: string;
  ip_address: string;
  groups: string[];
  status: string;
  ansible_user: string;
  updated_at: number;
}

interface HostInfo {
  name: string;
  ip?: string;
  lastSeen: number;
  reachable: boolean;
  os?: string;
  taskCount: number;
  failCount: number;
  changeCount: number;
  groups?: string[];
  user?: string;
}

function extractSessionHosts(events: AgentEvent[]): Map<string, HostInfo> {
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

  return hostMap;
}

function mergeHosts(persisted: PersistedHost[], sessionHosts: Map<string, HostInfo>): HostInfo[] {
  const merged = new Map<string, HostInfo>();

  for (const h of persisted) {
    const reachable = ["reachable", "configured", "verified"].includes(h.status);
    merged.set(h.hostname, {
      name: h.hostname,
      ip: h.ip_address || undefined,
      lastSeen: h.updated_at * 1000,
      reachable,
      taskCount: 0,
      failCount: 0,
      changeCount: 0,
      groups: h.groups,
      user: h.ansible_user || undefined,
    });
  }

  for (const [name, session] of sessionHosts) {
    const existing = merged.get(name);
    if (existing) {
      existing.taskCount = Math.max(existing.taskCount, session.taskCount);
      existing.failCount = Math.max(existing.failCount, session.failCount);
      existing.changeCount = Math.max(existing.changeCount, session.changeCount);
      existing.reachable = session.reachable;
      existing.lastSeen = Math.max(existing.lastSeen, session.lastSeen);
      if (session.os) existing.os = session.os;
    } else {
      merged.set(name, session);
    }
  }

  return Array.from(merged.values()).sort((a, b) => b.lastSeen - a.lastSeen);
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

      {(host.ip || host.os) && (
        <div className="flex items-center gap-2 text-[10px] text-zinc-500">
          {host.ip && <span className="font-mono">{host.ip}</span>}
          {host.os && (
            <span className="flex items-center gap-1">
              <HardDrive className="h-3 w-3" />
              {host.os}
            </span>
          )}
        </div>
      )}

      <div className="flex items-center gap-3 text-[10px] font-mono">
        {host.taskCount > 0 && <span className="text-zinc-500">{host.taskCount} tasks</span>}
        {host.changeCount > 0 && <span className="text-amber-400">{host.changeCount} changed</span>}
        {host.failCount > 0 && <span className="text-red-400">{host.failCount} failed</span>}
        {host.groups && host.groups.length > 0 && (
          <span className="text-zinc-600">{host.groups.join(", ")}</span>
        )}
        <span className="ml-auto text-zinc-600">{timeAgo(host.lastSeen)}</span>
      </div>
    </div>
  );
}

export function HostInventory({ events }: { events: AgentEvent[] }) {
  const [persisted, setPersisted] = useState<PersistedHost[]>([]);
  const [loading, setLoading] = useState(true);
  const [showSessionOnly, setShowSessionOnly] = useState(false);

  const loadPersisted = useCallback(async () => {
    try {
      const data = await request<PersistedHost[]>("/infrastructure/hosts");
      setPersisted(data);
    } catch {
      // API may not be ready
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadPersisted(); }, [loadPersisted]);

  const sessionHosts = useMemo(() => extractSessionHosts(events), [events]);
  const allHosts = useMemo(() => mergeHosts(persisted, sessionHosts), [persisted, sessionHosts]);

  const hosts = useMemo(() => {
    if (!showSessionOnly) return allHosts;
    const sessionNames = new Set(sessionHosts.keys());
    return allHosts.filter((h) => sessionNames.has(h.name));
  }, [allHosts, sessionHosts, showSessionOnly]);

  if (allHosts.length === 0 && !loading) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 p-6 text-center">
        <div className="rounded-xl bg-zinc-900/50 p-4 ring-1 ring-zinc-800">
          <Server className="h-8 w-8 text-zinc-600" />
        </div>
        <div>
          <p className="text-xs text-zinc-500">No Ansible-managed hosts</p>
          <p className="mt-1 text-[11px] text-zinc-600">
            Hosts appear here after running playbooks, collecting facts, or testing connectivity
          </p>
          <p className="mt-1 text-[10px] text-zinc-700">
            CLI-only activity (kubectl, tart, ssh) does not register hosts
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-3 space-y-2">
      <div className="flex items-center justify-between px-1 mb-1">
        <span className="text-[10px] text-zinc-500 uppercase tracking-wider font-medium">
          {hosts.length} host{hosts.length !== 1 ? "s" : ""}
          {showSessionOnly && " (this session)"}
        </span>
        <div className="flex items-center gap-1">
          {sessionHosts.size > 0 && (
            <button
              onClick={() => setShowSessionOnly(!showSessionOnly)}
              className={cn(
                "rounded px-1.5 py-0.5 text-[10px] transition-colors",
                showSessionOnly
                  ? "bg-zinc-700 text-zinc-200"
                  : "text-zinc-600 hover:text-zinc-400"
              )}
              title={showSessionOnly ? "Show all hosts" : "Show session hosts only"}
            >
              session
            </button>
          )}
          <button
            onClick={loadPersisted}
            className="rounded p-0.5 text-zinc-600 hover:text-zinc-400 transition-colors"
            title="Refresh"
          >
            <RefreshCw className="h-3 w-3" />
          </button>
        </div>
      </div>
      {hosts.length === 0 && showSessionOnly ? (
        <div className="text-center py-6">
          <p className="text-[11px] text-zinc-600">No Ansible-managed hosts in this session</p>
          <button
            onClick={() => setShowSessionOnly(false)}
            className="mt-1 text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            Show all hosts
          </button>
        </div>
      ) : (
        hosts.map((host) => (
          <HostCard key={host.name} host={host} />
        ))
      )}
    </div>
  );
}
