import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  ChevronRight,
  Cloud,
  Loader2,
  Plus,
  RefreshCw,
  Server,
  Trash2,
  Wifi,
  WifiOff,
  X,
} from "lucide-react";
import { request } from "@/api/client";
import { cn } from "@/lib/utils";

type Tab = "hosts" | "sources";

interface HostData {
  host_id: string;
  hostname: string;
  ip_address: string;
  groups: string[];
  status: string;
  ansible_user: string;
  source_id: string | null;
  updated_at: number;
}

interface DriftData {
  id: number;
  host_id: string;
  field: string;
  expected_value: string;
  actual_value: string;
}

interface InfraStats {
  hosts: number;
  hosts_with_facts: number;
  total_runs: number;
  unresolved_drifts: number;
  inventory_sources: number;
}

interface SourceData {
  source_id: string;
  name: string;
  plugin_type: string;
  config_yaml: string;
  regions: string[];
  last_synced_at: number | null;
  host_count: number;
  status: string;
}

interface TemplateData {
  plugin_type: string;
  name: string;
  description: string;
  required_collections: string[];
  required_env_vars: string[];
  optional_env_vars?: string[];
}

function statusIcon(status: string) {
  switch (status) {
    case "reachable":
    case "configured":
    case "verified":
      return <Wifi className="h-3.5 w-3.5 text-emerald-400" />;
    case "unreachable":
      return <WifiOff className="h-3.5 w-3.5 text-red-400" />;
    case "discovered":
      return <Cloud className="h-3.5 w-3.5 text-sky-400" />;
    default:
      return <Server className="h-3.5 w-3.5 text-zinc-500" />;
  }
}

function statusColor(status: string): string {
  switch (status) {
    case "reachable": return "text-emerald-400";
    case "configured": return "text-blue-400";
    case "verified": return "text-cyan-400";
    case "unreachable": return "text-red-400";
    case "discovered": return "text-sky-400";
    default: return "text-zinc-500";
  }
}

function timeAgo(ts: number | null): string {
  if (!ts) return "never";
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function sourceStatusBadge(status: string) {
  if (status === "synced") return "text-emerald-400 bg-emerald-950/30";
  if (status === "syncing") return "text-amber-400 bg-amber-950/30";
  if (status === "never_synced") return "text-zinc-500 bg-zinc-800/50";
  return "text-red-400 bg-red-950/30";
}

function sourceBadge(sourceId: string | null) {
  if (!sourceId) return null;
  return (
    <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[9px] font-medium bg-sky-950/30 text-sky-400">
      <Cloud className="h-2.5 w-2.5" />
      dynamic
    </span>
  );
}

export function HostsView() {
  const [tab, setTab] = useState<Tab>("hosts");
  const [hosts, setHosts] = useState<HostData[]>([]);
  const [drifts, setDrifts] = useState<DriftData[]>([]);
  const [stats, setStats] = useState<InfraStats | null>(null);
  const [sources, setSources] = useState<SourceData[]>([]);
  const [templates, setTemplates] = useState<TemplateData[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedHost, setSelectedHost] = useState<string | null>(null);
  const [showAddSource, setShowAddSource] = useState(false);
  const [refreshingSource, setRefreshingSource] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [hostsRes, driftRes, statsRes, sourcesRes] = await Promise.all([
        request<HostData[]>("/infrastructure/hosts"),
        request<DriftData[]>("/infrastructure/drift"),
        request<InfraStats>("/infrastructure/stats"),
        request<SourceData[]>("/inventory-sources/"),
      ]);
      setHosts(hostsRes);
      setDrifts(driftRes);
      setStats(statsRes);
      setSources(sourcesRes);
    } catch {
      // API may not be available yet
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    if (showAddSource && templates.length === 0) {
      request<TemplateData[]>("/inventory-sources/templates/list")
        .then(setTemplates)
        .catch(() => {});
    }
  }, [showAddSource, templates.length]);

  const handleRefreshSource = useCallback(async (sourceId: string) => {
    setRefreshingSource(sourceId);
    try {
      await request(`/inventory-sources/${sourceId}/refresh`, { method: "POST" });
      await refresh();
    } catch {
      // handled
    } finally {
      setRefreshingSource(null);
    }
  }, [refresh]);

  const handleDeleteSource = useCallback(async (sourceId: string) => {
    try {
      await request(`/inventory-sources/${sourceId}?remove_hosts=true`, { method: "DELETE" });
      await refresh();
    } catch {
      // handled
    }
  }, [refresh]);

  const groupedHosts = hosts.reduce<Record<string, HostData[]>>((acc, h) => {
    const groups = h.groups.length ? h.groups : ["ungrouped"];
    for (const g of groups) {
      if (!acc[g]) acc[g] = [];
      acc[g].push(h);
    }
    return acc;
  }, {});

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
        <div className="flex items-center gap-2">
          <Server className="h-4 w-4 text-zinc-400" />
          <h2 className="text-sm font-semibold text-zinc-200">Infrastructure</h2>
          {stats && (
            <span className="text-[10px] text-zinc-600">
              {stats.hosts} host{stats.hosts !== 1 ? "s" : ""} · {stats.total_runs} runs
            </span>
          )}
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

      {/* Tab bar */}
      <div className="flex border-b border-zinc-800">
        <button
          onClick={() => setTab("hosts")}
          className={cn(
            "flex-1 py-2 text-xs font-medium text-center transition-colors",
            tab === "hosts"
              ? "text-zinc-200 border-b-2 border-zinc-400"
              : "text-zinc-500 hover:text-zinc-400"
          )}
        >
          Hosts
        </button>
        <button
          onClick={() => setTab("sources")}
          className={cn(
            "flex-1 py-2 text-xs font-medium text-center transition-colors",
            tab === "sources"
              ? "text-zinc-200 border-b-2 border-zinc-400"
              : "text-zinc-500 hover:text-zinc-400"
          )}
        >
          Sources
          {sources.length > 0 && (
            <span className="ml-1.5 rounded-full bg-zinc-800 px-1.5 py-0.5 text-[9px]">
              {sources.length}
            </span>
          )}
        </button>
      </div>

      {tab === "hosts" ? (
        <HostsTab
          hosts={hosts}
          drifts={drifts}
          groupedHosts={groupedHosts}
          selectedHost={selectedHost}
          setSelectedHost={setSelectedHost}
          loading={loading}
        />
      ) : (
        <SourcesTab
          sources={sources}
          templates={templates}
          showAddSource={showAddSource}
          setShowAddSource={setShowAddSource}
          refreshingSource={refreshingSource}
          onRefresh={handleRefreshSource}
          onDelete={handleDeleteSource}
          onCreated={refresh}
        />
      )}

      {/* Footer */}
      {stats && (
        <div className="border-t border-zinc-800 px-4 py-2 flex items-center gap-4 text-[10px] text-zinc-600">
          <span>{stats.hosts_with_facts} with facts</span>
          <span>{stats.total_runs} total runs</span>
          {stats.unresolved_drifts > 0 && (
            <span className="text-amber-500">{stats.unresolved_drifts} drifts</span>
          )}
          {stats.inventory_sources > 0 && (
            <span className="text-sky-500">{stats.inventory_sources} source{stats.inventory_sources !== 1 ? "s" : ""}</span>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Hosts tab ───────────────────────────────────────────────────── */

function HostsTab({
  hosts,
  drifts,
  groupedHosts,
  selectedHost,
  setSelectedHost,
  loading,
}: {
  hosts: HostData[];
  drifts: DriftData[];
  groupedHosts: Record<string, HostData[]>;
  selectedHost: string | null;
  setSelectedHost: (id: string | null) => void;
  loading: boolean;
}) {
  return (
    <div className="flex-1 overflow-y-auto">
      {drifts.length > 0 && (
        <div className="border-b border-amber-800/30 bg-amber-950/10 px-4 py-2">
          <div className="flex items-center gap-2 text-xs text-amber-400">
            <AlertTriangle className="h-3.5 w-3.5" />
            <span>{drifts.length} drift warning{drifts.length !== 1 ? "s" : ""}</span>
          </div>
          <div className="mt-1 space-y-0.5">
            {drifts.slice(0, 3).map((d) => (
              <div key={d.id} className="text-[10px] text-amber-500/70">
                {d.host_id}.{d.field}: expected {d.expected_value}, got {d.actual_value}
              </div>
            ))}
          </div>
        </div>
      )}

      {hosts.length === 0 && !loading ? (
        <div className="flex flex-col items-center justify-center h-full text-center px-8">
          <Server className="h-10 w-10 text-zinc-800 mb-3" />
          <p className="text-sm text-zinc-500">No hosts discovered yet</p>
          <p className="text-xs text-zinc-700 mt-1">
            Start a chat session and connect to a host, or add a cloud inventory source.
          </p>
        </div>
      ) : (
        <div className="p-2 space-y-3">
          {Object.entries(groupedHosts).map(([group, groupHosts]) => (
            <div key={group}>
              <div className="px-2 py-1 text-[10px] font-medium uppercase tracking-wider text-zinc-600">
                {group} ({groupHosts.length})
              </div>
              <div className="space-y-0.5">
                {groupHosts.map((h) => (
                  <button
                    key={h.host_id}
                    onClick={() => setSelectedHost(selectedHost === h.host_id ? null : h.host_id)}
                    className={cn(
                      "flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-xs transition-colors",
                      selectedHost === h.host_id
                        ? "bg-zinc-800/80 text-zinc-100"
                        : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-300"
                    )}
                  >
                    {statusIcon(h.status)}
                    <div className="flex-1 min-w-0">
                      <span className="flex items-center gap-1.5 truncate font-medium">
                        {h.hostname}
                        {sourceBadge(h.source_id)}
                      </span>
                      <span className="block text-[10px] text-zinc-600">
                        {h.ip_address || "no IP"} · {h.ansible_user || "no user"} · {timeAgo(h.updated_at)}
                      </span>
                    </div>
                    <span className={cn("text-[10px] capitalize", statusColor(h.status))}>
                      {h.status}
                    </span>
                    <ChevronRight className={cn(
                      "h-3 w-3 text-zinc-700 transition-transform",
                      selectedHost === h.host_id && "rotate-90"
                    )} />
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Sources tab ─────────────────────────────────────────────────── */

function SourcesTab({
  sources,
  templates,
  showAddSource,
  setShowAddSource,
  refreshingSource,
  onRefresh,
  onDelete,
  onCreated,
}: {
  sources: SourceData[];
  templates: TemplateData[];
  showAddSource: boolean;
  setShowAddSource: (v: boolean) => void;
  refreshingSource: string | null;
  onRefresh: (id: string) => void;
  onDelete: (id: string) => void;
  onCreated: () => void;
}) {
  return (
    <div className="flex-1 overflow-y-auto">
      {showAddSource && (
        <AddSourceForm
          templates={templates}
          onClose={() => setShowAddSource(false)}
          onCreated={() => { setShowAddSource(false); onCreated(); }}
        />
      )}

      {!showAddSource && (
        <div className="p-3">
          <button
            onClick={() => setShowAddSource(true)}
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-zinc-700 py-3 text-xs text-zinc-500 hover:border-zinc-500 hover:text-zinc-300 transition-colors"
          >
            <Plus className="h-3.5 w-3.5" />
            Add Inventory Source
          </button>
        </div>
      )}

      {sources.length === 0 && !showAddSource ? (
        <div className="flex flex-col items-center justify-center px-8 py-12 text-center">
          <Cloud className="h-10 w-10 text-zinc-800 mb-3" />
          <p className="text-sm text-zinc-500">No inventory sources configured</p>
          <p className="text-xs text-zinc-700 mt-1">
            Add a cloud source to auto-discover AWS, Azure, or GCP hosts.
          </p>
        </div>
      ) : (
        <div className="p-2 space-y-1">
          {sources.map((s) => (
            <div
              key={s.source_id}
              className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Cloud className="h-3.5 w-3.5 text-sky-400" />
                  <span className="text-xs font-medium text-zinc-200">{s.name}</span>
                  <span className={cn(
                    "rounded px-1.5 py-0.5 text-[9px] font-medium",
                    sourceStatusBadge(s.status),
                  )}>
                    {s.status === "never_synced" ? "not synced" : s.status}
                  </span>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => onRefresh(s.source_id)}
                    disabled={refreshingSource === s.source_id}
                    className="rounded p-1 text-zinc-600 hover:bg-zinc-800 hover:text-zinc-300 transition-colors"
                    title="Refresh"
                  >
                    {refreshingSource === s.source_id
                      ? <Loader2 className="h-3 w-3 animate-spin" />
                      : <RefreshCw className="h-3 w-3" />}
                  </button>
                  <button
                    onClick={() => onDelete(s.source_id)}
                    className="rounded p-1 text-zinc-600 hover:bg-red-950/50 hover:text-red-400 transition-colors"
                    title="Delete source and its hosts"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              </div>
              <div className="mt-1.5 flex items-center gap-3 text-[10px] text-zinc-600">
                <span>{s.plugin_type}</span>
                <span>{s.host_count} host{s.host_count !== 1 ? "s" : ""}</span>
                <span>synced {timeAgo(s.last_synced_at)}</span>
              </div>
              {s.status.startsWith("error") && (
                <div className="mt-1.5 rounded bg-red-950/20 px-2 py-1 text-[10px] text-red-400">
                  {s.status}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Add source form ─────────────────────────────────────────────── */

function AddSourceForm({
  templates,
  onClose,
  onCreated,
}: {
  templates: TemplateData[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [name, setName] = useState("");
  const [selectedTemplate, setSelectedTemplate] = useState<TemplateData | null>(null);
  const [configYaml, setConfigYaml] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleTemplateSelect = async (pluginType: string) => {
    const tmpl = templates.find((t) => t.plugin_type === pluginType);
    setSelectedTemplate(tmpl || null);
    setName(tmpl?.name || "");
    try {
      const full = await request<{ default_config: string; plugin_type: string }>(
        `/inventory-sources/templates/${pluginType}`,
      );
      setConfigYaml(full.default_config || "");
    } catch {
      setConfigYaml("");
    }
  };

  const handleSubmit = async () => {
    if (!name.trim()) { setError("Name is required"); return; }
    if (!selectedTemplate) { setError("Select a template"); return; }

    setSaving(true);
    setError(null);
    try {
      await request("/inventory-sources/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          plugin_type: selectedTemplate.plugin_type,
          config_yaml: configYaml,
        }),
      });
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create source");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="border-b border-zinc-800 bg-zinc-900/80 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-zinc-300">Add Inventory Source</h3>
        <button onClick={onClose} className="text-zinc-600 hover:text-zinc-400">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Template picker */}
      <div className="grid grid-cols-2 gap-1.5">
        {templates.filter((t) => t.plugin_type !== "generic").map((t) => (
          <button
            key={t.plugin_type}
            onClick={() => handleTemplateSelect(t.plugin_type)}
            className={cn(
              "rounded-md border px-2.5 py-2 text-left text-[11px] transition-colors",
              selectedTemplate?.plugin_type === t.plugin_type
                ? "border-sky-600 bg-sky-950/20 text-sky-300"
                : "border-zinc-800 text-zinc-500 hover:border-zinc-600 hover:text-zinc-300"
            )}
          >
            <span className="block font-medium">{t.name}</span>
            <span className="block text-[9px] text-zinc-600 mt-0.5">{t.plugin_type}</span>
          </button>
        ))}
        <button
          onClick={() => handleTemplateSelect("generic")}
          className={cn(
            "rounded-md border px-2.5 py-2 text-left text-[11px] transition-colors",
            selectedTemplate?.plugin_type === "generic"
              ? "border-sky-600 bg-sky-950/20 text-sky-300"
              : "border-zinc-800 text-zinc-500 hover:border-zinc-600 hover:text-zinc-300"
          )}
        >
          <span className="block font-medium">Custom</span>
          <span className="block text-[9px] text-zinc-600 mt-0.5">Any Ansible plugin</span>
        </button>
      </div>

      {/* Setup hints */}
      {selectedTemplate && selectedTemplate.plugin_type !== "generic" && (
        <div className="rounded-md bg-zinc-800/50 px-3 py-2 space-y-1">
          <p className="text-[10px] text-zinc-400 font-medium">Required setup</p>
          <p className="text-[10px] text-zinc-500">
            Collection: <code className="text-zinc-400">{selectedTemplate.required_collections.join(", ")}</code>
          </p>
          {selectedTemplate.required_env_vars.length > 0 && (
            <p className="text-[10px] text-zinc-500">
              Env vars: <code className="text-zinc-400">{selectedTemplate.required_env_vars.join(", ")}</code>
            </p>
          )}
        </div>
      )}

      {/* Name */}
      {selectedTemplate && (
        <>
          <input
            type="text"
            placeholder="Source name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs text-zinc-200 placeholder-zinc-600 focus:border-zinc-500 focus:outline-none"
          />

          {/* Config editor */}
          <div className="space-y-1">
            <label className="text-[10px] text-zinc-500 font-medium">Plugin configuration (YAML)</label>
            <textarea
              value={configYaml}
              onChange={(e) => setConfigYaml(e.target.value)}
              rows={8}
              className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-[11px] font-mono text-zinc-300 placeholder-zinc-600 focus:border-zinc-500 focus:outline-none resize-y"
              spellCheck={false}
            />
          </div>

          {error && (
            <p className="text-[10px] text-red-400">{error}</p>
          )}

          <div className="flex justify-end gap-2">
            <button
              onClick={onClose}
              className="rounded-md px-3 py-1.5 text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSubmit}
              disabled={saving}
              className="rounded-md bg-sky-600 px-3 py-1.5 text-xs text-white hover:bg-sky-500 disabled:opacity-50 transition-colors"
            >
              {saving ? "Saving..." : "Add Source"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
