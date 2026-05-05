import { useCallback, useEffect, useState } from "react";
import {
  Brain,
  CheckCircle2,
  ChevronRight,
  FileText,
  GitBranch,
  Lightbulb,
  RefreshCw,
  ScrollText,
  Shield,
  XCircle,
  Zap,
} from "lucide-react";
import { request } from "@/api/client";
import { cn } from "@/lib/utils";

interface KnowledgeStats {
  recipes: number;
  error_resolutions: number;
  corrections: number;
  reflections: number;
  rules: number;
  total: number;
}

interface RecentError {
  pattern: string;
  module: string;
  resolution: string;
  resolved: boolean;
  count: number;
}

interface GraphNode {
  id: string;
  type: string;
  label: string;
  confidence?: number;
  use_count?: number;
}

interface GraphEdge {
  source: string;
  target: string;
  type: string;
}

type Tab = "overview" | "recipes" | "errors" | "memory";

const TYPE_META: Record<string, { icon: typeof Brain; color: string; label: string }> = {
  recipe: { icon: ScrollText, color: "text-emerald-400", label: "Recipes" },
  error: { icon: XCircle, color: "text-red-400", label: "Error Fixes" },
  error_resolution: { icon: CheckCircle2, color: "text-blue-400", label: "Resolutions" },
  correction: { icon: GitBranch, color: "text-amber-400", label: "Corrections" },
  reflection: { icon: Lightbulb, color: "text-purple-400", label: "Reflections" },
  rule: { icon: Shield, color: "text-cyan-400", label: "Rules" },
  module: { icon: Zap, color: "text-sky-400", label: "Modules" },
};

function confidenceBar(confidence: number) {
  const pct = Math.round(confidence * 100);
  const color =
    pct >= 70 ? "bg-emerald-500" : pct >= 40 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-1.5">
      <div className="h-1 w-16 rounded-full bg-zinc-800 overflow-hidden">
        <div className={cn("h-full rounded-full", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[9px] text-zinc-600">{pct}%</span>
    </div>
  );
}

function timeAgo(ts: number): string {
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function KnowledgeView() {
  const [tab, setTab] = useState<Tab>("overview");
  const [stats, setStats] = useState<KnowledgeStats | null>(null);
  const [errors, setErrors] = useState<RecentError[]>([]);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [workspaceMemory, setWorkspaceMemory] = useState<string>("");
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [statsRes, graphRes] = await Promise.all([
        request<{ stats: KnowledgeStats; recent_errors: RecentError[] }>("/knowledge/stats"),
        request<{ nodes: GraphNode[]; edges: GraphEdge[] }>("/knowledge/graph"),
      ]);
      setStats(statsRes.stats);
      setErrors(statsRes.recent_errors);
      setNodes(graphRes.nodes);
      setEdges(graphRes.edges);
    } catch {
      // API may not be ready
    }
    try {
      const memRes = await request<{ content: string }>("/knowledge/workspace-memory");
      setWorkspaceMemory(memRes.content || "");
    } catch {
      // Endpoint may not exist yet
    }
    setLoading(false);
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const modules = nodes.filter((n) => n.type === "module");
  const recipes = nodes.filter((n) => n.type === "recipe");
  const errorNodes = nodes.filter((n) => n.type === "error");
  const reflections = nodes.filter((n) => n.type === "reflection");
  const rules = nodes.filter((n) => n.type === "rule");

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-zinc-400" />
          <h2 className="text-sm font-semibold text-zinc-200">Knowledge Base</h2>
          {stats && (
            <span className="text-[10px] text-zinc-600">
              {stats.total} experience{stats.total !== 1 ? "s" : ""}
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

      <div className="flex border-b border-zinc-800">
        {(["overview", "recipes", "errors", "memory"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "flex-1 py-2 text-xs font-medium text-center transition-colors capitalize",
              tab === t
                ? "text-zinc-200 border-b-2 border-zinc-400"
                : "text-zinc-500 hover:text-zinc-400"
            )}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto">
        {tab === "overview" && stats && (
          <OverviewTab
            stats={stats}
            moduleCount={modules.length}
            errors={errors}
          />
        )}
        {tab === "recipes" && (
          <NodeListTab nodes={recipes} type="recipe" edges={edges} allNodes={nodes} />
        )}
        {tab === "errors" && (
          <ErrorsTab errors={errors} nodes={errorNodes} reflections={reflections} rules={rules} />
        )}
        {tab === "memory" && (
          <WorkspaceMemoryTab content={workspaceMemory} />
        )}
        {!stats && !loading && (
          <div className="flex flex-col items-center justify-center h-full text-center px-8">
            <Brain className="h-10 w-10 text-zinc-800 mb-3" />
            <p className="text-sm text-zinc-500">No knowledge yet</p>
            <p className="text-xs text-zinc-700 mt-1">
              Start chatting and the agent will learn from each session.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function OverviewTab({
  stats,
  moduleCount,
  errors,
}: {
  stats: KnowledgeStats;
  moduleCount: number;
  errors: RecentError[];
}) {
  const cards = [
    { label: "Recipes", value: stats.recipes, icon: ScrollText, color: "text-emerald-400", bg: "bg-emerald-950/20" },
    { label: "Error Fixes", value: stats.error_resolutions, icon: CheckCircle2, color: "text-blue-400", bg: "bg-blue-950/20" },
    { label: "Reflections", value: stats.reflections, icon: Lightbulb, color: "text-purple-400", bg: "bg-purple-950/20" },
    { label: "Rules", value: stats.rules, icon: Shield, color: "text-cyan-400", bg: "bg-cyan-950/20" },
    { label: "Corrections", value: stats.corrections, icon: GitBranch, color: "text-amber-400", bg: "bg-amber-950/20" },
    { label: "Modules", value: moduleCount, icon: Zap, color: "text-sky-400", bg: "bg-sky-950/20" },
  ];

  return (
    <div className="p-4 space-y-4">
      <div className="grid grid-cols-3 gap-2">
        {cards.map((c) => (
          <div key={c.label} className={cn("rounded-lg border border-zinc-800 p-3", c.bg)}>
            <div className="flex items-center gap-1.5 mb-1">
              <c.icon className={cn("h-3 w-3", c.color)} />
              <span className="text-[10px] text-zinc-500">{c.label}</span>
            </div>
            <span className={cn("text-lg font-semibold", c.color)}>{c.value}</span>
          </div>
        ))}
      </div>

      {stats.total > 0 && (
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3">
          <p className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider mb-1">
            How it works
          </p>
          <p className="text-xs text-zinc-400 leading-relaxed">
            The agent learns from every session. Successful playbook runs become
            <span className="text-emerald-400"> recipes</span>. Failed attempts that get resolved
            become <span className="text-blue-400">error fixes</span>. User rejections teach
            <span className="text-amber-400"> corrections</span>. All of this feeds back into
            future decisions — the agent gets smarter with use.
          </p>
        </div>
      )}

      {errors.length > 0 && (
        <div>
          <p className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider mb-2">
            Recent Error Resolutions
          </p>
          <div className="space-y-1.5">
            {errors.slice(0, 5).map((e, i) => (
              <div key={i} className="rounded-md border border-zinc-800 bg-zinc-900/50 px-3 py-2">
                <div className="flex items-start gap-2">
                  {e.resolved ? (
                    <CheckCircle2 className="h-3 w-3 text-emerald-500 mt-0.5 shrink-0" />
                  ) : (
                    <XCircle className="h-3 w-3 text-red-500 mt-0.5 shrink-0" />
                  )}
                  <div className="min-w-0">
                    <p className="text-[11px] text-zinc-400 truncate">{e.pattern}</p>
                    <p className="text-[10px] text-zinc-600 mt-0.5 truncate">{e.resolution}</p>
                    {e.module && (
                      <span className="inline-block mt-1 rounded px-1.5 py-0.5 text-[9px] bg-zinc-800 text-zinc-500">
                        {e.module}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function NodeListTab({
  nodes,
  type,
  edges,
  allNodes,
}: {
  nodes: GraphNode[];
  type: string;
  edges: GraphEdge[];
  allNodes: GraphNode[];
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const meta = TYPE_META[type] || TYPE_META.recipe;
  const Icon = meta.icon;

  if (nodes.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full px-8 text-center">
        <Icon className={cn("h-10 w-10 text-zinc-800 mb-3")} />
        <p className="text-sm text-zinc-500">No {meta.label.toLowerCase()} yet</p>
        <p className="text-xs text-zinc-700 mt-1">
          These are captured automatically during chat sessions.
        </p>
      </div>
    );
  }

  return (
    <div className="p-2 space-y-1">
      {nodes.map((n) => {
        const relatedEdges = edges.filter((e) => e.source === n.id);
        const relatedModules = relatedEdges
          .map((e) => allNodes.find((nn) => nn.id === e.target))
          .filter(Boolean);
        const isOpen = expanded === n.id;

        return (
          <div key={n.id} className="rounded-md border border-zinc-800 bg-zinc-900/50">
            <button
              onClick={() => setExpanded(isOpen ? null : n.id)}
              className="flex w-full items-center gap-2 px-3 py-2 text-left"
            >
              <Icon className={cn("h-3 w-3 shrink-0", meta.color)} />
              <span className="flex-1 text-xs text-zinc-300 truncate">{n.label}</span>
              {n.confidence != null && confidenceBar(n.confidence)}
              <ChevronRight className={cn(
                "h-3 w-3 text-zinc-700 transition-transform shrink-0",
                isOpen && "rotate-90"
              )} />
            </button>
            {isOpen && (
              <div className="border-t border-zinc-800 px-3 py-2 space-y-1">
                {n.use_count != null && (
                  <p className="text-[10px] text-zinc-600">Used {n.use_count} time{n.use_count !== 1 ? "s" : ""}</p>
                )}
                {relatedModules.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {relatedModules.map((m) => m && (
                      <span key={m.id} className="rounded px-1.5 py-0.5 text-[9px] bg-sky-950/30 text-sky-400">
                        {m.label}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function ErrorsTab({
  errors,
  nodes,
  reflections,
  rules,
}: {
  errors: RecentError[];
  nodes: GraphNode[];
  reflections: GraphNode[];
  rules: GraphNode[];
}) {
  return (
    <div className="p-3 space-y-4">
      {rules.length > 0 && (
        <div>
          <p className="text-[10px] font-medium text-cyan-500 uppercase tracking-wider mb-2">
            Learned Rules ({rules.length})
          </p>
          <div className="space-y-1">
            {rules.map((r) => (
              <div key={r.id} className="flex items-start gap-2 rounded-md border border-zinc-800 bg-zinc-900/50 px-3 py-2">
                <Shield className="h-3 w-3 text-cyan-400 mt-0.5 shrink-0" />
                <span className="text-[11px] text-zinc-300">{r.label}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {errors.length > 0 && (
        <div>
          <p className="text-[10px] font-medium text-blue-500 uppercase tracking-wider mb-2">
            Error Resolutions ({errors.length})
          </p>
          <div className="space-y-1">
            {errors.map((e, i) => (
              <div key={i} className="rounded-md border border-zinc-800 bg-zinc-900/50 px-3 py-2">
                <div className="flex items-center gap-1.5 mb-1">
                  {e.resolved ? (
                    <CheckCircle2 className="h-3 w-3 text-emerald-500" />
                  ) : (
                    <XCircle className="h-3 w-3 text-red-500" />
                  )}
                  <span className="text-[11px] text-zinc-300 truncate">{e.pattern}</span>
                </div>
                <p className="text-[10px] text-zinc-600 ml-4.5">{e.resolution}</p>
                <div className="flex items-center gap-2 mt-1 ml-4.5">
                  {e.module && (
                    <span className="rounded px-1.5 py-0.5 text-[9px] bg-zinc-800 text-zinc-500">{e.module}</span>
                  )}
                  {e.count > 0 && (
                    <span className="text-[9px] text-zinc-600">applied {e.count}x</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {nodes.length === 0 && errors.length === 0 && (
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <CheckCircle2 className="h-10 w-10 text-zinc-800 mb-3" />
          <p className="text-sm text-zinc-500">No errors resolved yet</p>
        </div>
      )}

      {reflections.length > 0 && (
        <div>
          <p className="text-[10px] font-medium text-purple-500 uppercase tracking-wider mb-2">
            Reflections ({reflections.length})
          </p>
          <div className="space-y-1">
            {reflections.slice(0, 15).map((r) => (
              <div key={r.id} className="flex items-start gap-2 rounded-md border border-zinc-800 bg-zinc-900/50 px-3 py-2">
                <Lightbulb className="h-3 w-3 text-purple-400 mt-0.5 shrink-0" />
                <div className="min-w-0">
                  <span className="text-[11px] text-zinc-300 block truncate">{r.label}</span>
                  {r.confidence != null && <div className="mt-1">{confidenceBar(r.confidence)}</div>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function WorkspaceMemoryTab({ content }: { content: string }) {
  if (!content.trim()) {
    return (
      <div className="flex flex-col items-center justify-center h-full px-8 text-center">
        <FileText className="h-10 w-10 text-zinc-800 mb-3" />
        <p className="text-sm text-zinc-500">No workspace memory yet</p>
        <p className="text-xs text-zinc-700 mt-1 leading-relaxed">
          The agent stores environment facts, SSH quirks, conventions, and
          lessons learned here. It builds up automatically across sessions.
        </p>
      </div>
    );
  }

  return (
    <div className="p-3 space-y-3">
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3">
        <div className="flex items-center gap-2 mb-2">
          <FileText className="h-3.5 w-3.5 text-emerald-400" />
          <span className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider">
            MEMORY.md
          </span>
          <span className="ml-auto text-[9px] text-zinc-600">
            {content.length} / 3,000 chars
          </span>
        </div>
        <div className="h-0.5 bg-zinc-800 rounded-full overflow-hidden mb-3">
          <div
            className="h-full bg-emerald-600 rounded-full"
            style={{ width: `${Math.min((content.length / 3000) * 100, 100)}%` }}
          />
        </div>
        <pre className="text-[11px] font-mono text-zinc-300 whitespace-pre-wrap leading-relaxed">
          {content}
        </pre>
      </div>
    </div>
  );
}
