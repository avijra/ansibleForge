import {
  Brain,
  Database,
  AlertTriangle,
  CheckCircle2,
  BookOpen,
  Lightbulb,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
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
  count: number;
  resolution?: string;
}

interface GraphNode {
  id: string;
  type: string;
  label: string;
  confidence?: number;
  use_count?: number;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
}

interface GraphEdge {
  source: string;
  target: string;
  type: string;
}

const NODE_COLORS: Record<string, string> = {
  recipe: "#34d399",
  error: "#f87171",
  correction: "#fbbf24",
  reflection: "#a78bfa",
  rule: "#60a5fa",
  module: "#94a3b8",
};

const NODE_RADIUS: Record<string, number> = {
  recipe: 8,
  error: 7,
  correction: 7,
  reflection: 6,
  rule: 9,
  module: 5,
};

function ForceGraph({
  nodes: rawNodes,
  edges,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animRef = useRef<number>(0);
  const nodesRef = useRef<GraphNode[]>([]);
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null);
  const [dimensions, setDimensions] = useState({ w: 400, h: 300 });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      setDimensions({ w: width, h: height });
    });
    ro.observe(canvas.parentElement!);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    nodesRef.current = rawNodes.map((n) => ({
      ...n,
      x: dimensions.w / 2 + (Math.random() - 0.5) * dimensions.w * 0.6,
      y: dimensions.h / 2 + (Math.random() - 0.5) * dimensions.h * 0.6,
      vx: 0,
      vy: 0,
    }));
  }, [rawNodes, dimensions]);

  const nodeMap = useCallback(() => {
    const map = new Map<string, GraphNode>();
    for (const n of nodesRef.current) map.set(n.id, n);
    return map;
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.width = dimensions.w * 2;
    canvas.height = dimensions.h * 2;
    const ctx = canvas.getContext("2d")!;
    ctx.scale(2, 2);

    let running = true;

    function tick() {
      if (!running) return;
      const nodes = nodesRef.current;
      const cx = dimensions.w / 2;
      const cy = dimensions.h / 2;

      for (const n of nodes) {
        n.vx = (n.vx || 0) * 0.9;
        n.vy = (n.vy || 0) * 0.9;
        const dx = cx - (n.x || 0);
        const dy = cy - (n.y || 0);
        n.vx! += dx * 0.001;
        n.vy! += dy * 0.001;
      }

      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i], b = nodes[j];
          const ddx = (b.x || 0) - (a.x || 0);
          const ddy = (b.y || 0) - (a.y || 0);
          const dist = Math.sqrt(ddx * ddx + ddy * ddy) || 1;
          const force = 800 / (dist * dist);
          const fx = (ddx / dist) * force;
          const fy = (ddy / dist) * force;
          a.vx! -= fx;
          a.vy! -= fy;
          b.vx! += fx;
          b.vy! += fy;
        }
      }

      const map = nodeMap();
      for (const e of edges) {
        const s = map.get(e.source);
        const t = map.get(e.target);
        if (!s || !t) continue;
        const ddx = (t.x || 0) - (s.x || 0);
        const ddy = (t.y || 0) - (s.y || 0);
        const dist = Math.sqrt(ddx * ddx + ddy * ddy) || 1;
        const force = (dist - 80) * 0.005;
        const fx = (ddx / dist) * force;
        const fy = (ddy / dist) * force;
        s.vx! += fx;
        s.vy! += fy;
        t.vx! -= fx;
        t.vy! -= fy;
      }

      for (const n of nodes) {
        n.x = (n.x || 0) + (n.vx || 0);
        n.y = (n.y || 0) + (n.vy || 0);
        n.x = Math.max(20, Math.min(dimensions.w - 20, n.x!));
        n.y = Math.max(20, Math.min(dimensions.h - 20, n.y!));
      }

      ctx.clearRect(0, 0, dimensions.w, dimensions.h);

      for (const e of edges) {
        const s = map.get(e.source);
        const t = map.get(e.target);
        if (!s || !t) continue;
        ctx.beginPath();
        ctx.moveTo(s.x!, s.y!);
        ctx.lineTo(t.x!, t.y!);
        ctx.strokeStyle = "rgba(63, 63, 70, 0.5)";
        ctx.lineWidth = 0.5;
        ctx.stroke();
      }

      for (const n of nodes) {
        const r = NODE_RADIUS[n.type] || 6;
        const color = NODE_COLORS[n.type] || "#71717a";
        ctx.beginPath();
        ctx.arc(n.x!, n.y!, r, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
        ctx.strokeStyle = "rgba(0,0,0,0.3)";
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      animRef.current = requestAnimationFrame(tick);
    }

    animRef.current = requestAnimationFrame(tick);
    return () => {
      running = false;
      cancelAnimationFrame(animRef.current);
    };
  }, [dimensions, edges, nodeMap]);

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      let found: GraphNode | null = null;
      for (const n of nodesRef.current) {
        const dx = (n.x || 0) - mx;
        const dy = (n.y || 0) - my;
        if (dx * dx + dy * dy < 144) {
          found = n;
          break;
        }
      }
      setHoveredNode(found);
    },
    []
  );

  return (
    <div className="relative w-full h-full min-h-[250px]">
      <canvas
        ref={canvasRef}
        className="w-full h-full"
        style={{ display: "block" }}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoveredNode(null)}
      />
      {hoveredNode && (
        <div className="absolute top-2 left-2 rounded-lg bg-zinc-900/95 border border-zinc-700 px-3 py-2 pointer-events-none z-10">
          <div className="flex items-center gap-2">
            <div
              className="h-3 w-3 rounded-full"
              style={{ backgroundColor: NODE_COLORS[hoveredNode.type] }}
            />
            <span className="text-[10px] text-zinc-500 uppercase">{hoveredNode.type}</span>
          </div>
          <div className="text-xs font-mono text-zinc-200 mt-1 max-w-[200px] truncate">
            {hoveredNode.label}
          </div>
          {hoveredNode.confidence != null && (
            <div className="text-[10px] text-zinc-500 mt-0.5">
              confidence: {Math.round(hoveredNode.confidence * 100)}%
            </div>
          )}
        </div>
      )}
      <div className="absolute bottom-2 right-2 flex gap-3 text-[9px] text-zinc-600">
        {Object.entries(NODE_COLORS).map(([type, color]) => (
          <div key={type} className="flex items-center gap-1">
            <div className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
            {type}
          </div>
        ))}
      </div>
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  color,
}: {
  icon: typeof Database;
  label: string;
  value: number;
  color: string;
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3">
      <div className="flex items-center gap-2 mb-2">
        <Icon className={cn("h-4 w-4", color)} />
        <span className="text-[10px] text-zinc-500 uppercase tracking-wider">{label}</span>
      </div>
      <span className="text-2xl font-mono font-medium text-zinc-200">{value}</span>
    </div>
  );
}

export function KnowledgeExplorer() {
  const [stats, setStats] = useState<KnowledgeStats | null>(null);
  const [errors, setErrors] = useState<RecentError[]>([]);
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
  const [graphEdges, setGraphEdges] = useState<GraphEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [showGraph, setShowGraph] = useState(true);
  const [showStats, setShowStats] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setFetchError(null);
    try {
      const { BACKEND_ORIGIN: origin } = await import("@/api/client");
      const base = import.meta.env.VITE_API_BASE || origin;
      const headers: Record<string, string> = {};
      const apiKey = import.meta.env.VITE_API_KEY;
      if (apiKey) headers["X-API-Key"] = apiKey;

      const [statsRes, graphRes] = await Promise.all([
        fetch(`${base}/api/v1/knowledge/stats`, { headers }),
        fetch(`${base}/api/v1/knowledge/graph`, { headers }),
      ]);
      if (statsRes.ok) {
        const data = await statsRes.json();
        setStats(data.stats || null);
        setErrors(data.recent_errors || []);
      }
      if (graphRes.ok) {
        const data = await graphRes.json();
        setGraphNodes(data.nodes || []);
        setGraphEdges(data.edges || []);
      }
    } catch (err) {
      setFetchError(err instanceof Error ? err.message : "Failed to load experience data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll, refreshKey]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="h-5 w-5 border-2 border-zinc-700 border-t-zinc-400 rounded-full animate-spin" />
      </div>
    );
  }

  if (fetchError) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 p-6 text-center">
        <p className="text-xs text-red-400">Failed to load experience data</p>
        <p className="text-xs text-zinc-500">{fetchError}</p>
        <button
          onClick={() => setRefreshKey((k) => k + 1)}
          className="flex items-center gap-1.5 rounded-md bg-zinc-800 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-700 transition-colors"
        >
          <RefreshCw className="h-3 w-3" />
          Retry
        </button>
      </div>
    );
  }

  if (!stats || stats.total === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 p-6 text-center">
        <div className="rounded-xl bg-zinc-900/50 p-4 ring-1 ring-zinc-800">
          <Brain className="h-8 w-8 text-zinc-600" />
        </div>
        <div>
          <p className="text-xs text-zinc-500">Experience store is building</p>
          <p className="mt-1 text-[11px] text-zinc-600">
            As you run playbooks, fix errors, and refine outputs, Tuyere learns
            from every interaction automatically
          </p>
        </div>
      </div>
    );
  }

  const hasGraph = graphNodes.length > 0;

  return (
    <div className="p-3 space-y-3">
      <div className="flex justify-end">
        <button
          onClick={() => setRefreshKey((k) => k + 1)}
          className="flex items-center gap-1 rounded-md px-2 py-1 text-[10px] text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300 transition-colors"
          title="Refresh experience data"
        >
          <RefreshCw className="h-3 w-3" />
          Refresh
        </button>
      </div>

      {hasGraph && (
        <div>
          <button
            onClick={() => setShowGraph(!showGraph)}
            className="flex items-center gap-1.5 text-[10px] text-zinc-500 uppercase tracking-wider font-medium mb-2 hover:text-zinc-300 transition-colors"
          >
            {showGraph ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            Experience Map ({graphNodes.length} nodes)
          </button>
          {showGraph && (
            <div className="rounded-lg border border-zinc-800 bg-zinc-950 h-[280px] overflow-hidden">
              <ForceGraph nodes={graphNodes} edges={graphEdges} />
            </div>
          )}
        </div>
      )}

      <div>
        <button
          onClick={() => setShowStats(!showStats)}
          className="flex items-center gap-1.5 text-[10px] text-zinc-500 uppercase tracking-wider font-medium mb-2 hover:text-zinc-300 transition-colors"
        >
          {showStats ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          Learnings
        </button>
        {showStats && (
          <>
            <div className="grid grid-cols-2 gap-2">
              <StatCard icon={BookOpen} label="Recipes" value={stats.recipes} color="text-emerald-400" />
              <StatCard icon={AlertTriangle} label="Error Fixes" value={stats.error_resolutions} color="text-red-400" />
              <StatCard icon={Sparkles} label="Corrections" value={stats.corrections} color="text-amber-400" />
              <StatCard icon={Lightbulb} label="Rules" value={stats.rules} color="text-blue-400" />
            </div>

            <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3 mt-2">
              <div className="flex items-center gap-2 mb-1">
                <Database className="h-3.5 w-3.5 text-zinc-500" />
                <span className="text-[10px] text-zinc-500 uppercase tracking-wider font-medium">
                  Total Experiences
                </span>
              </div>
              <span className="text-lg font-mono text-zinc-300">{stats.total}</span>
              {stats.reflections > 0 && (
                <span className="ml-2 text-[10px] text-zinc-600">
                  ({stats.reflections} reflections)
                </span>
              )}
            </div>
          </>
        )}
      </div>

      {errors.length > 0 && (
        <div>
          <h3 className="text-[10px] text-zinc-500 uppercase tracking-wider font-medium mb-2 px-1">
            Recent Error Resolutions
          </h3>
          <div className="space-y-2">
            {errors.map((err, i) => (
              <div
                key={i}
                className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-2.5 space-y-1.5"
              >
                <div className="flex items-start gap-2">
                  <AlertTriangle className="h-3.5 w-3.5 text-red-400 shrink-0 mt-0.5" />
                  <span className="text-[11px] text-zinc-300 font-mono leading-relaxed">
                    {err.pattern}
                  </span>
                </div>
                {err.module && (
                  <div className="flex items-center gap-2 ml-5 text-[10px]">
                    <span className="text-zinc-600">tool: {err.module}</span>
                    {err.count > 0 && (
                      <>
                        <span className="text-zinc-700">|</span>
                        <span className="text-zinc-600">used {err.count}x</span>
                      </>
                    )}
                  </div>
                )}
                {err.resolution && (
                  <div className="ml-5 flex items-start gap-1.5 mt-1">
                    <CheckCircle2 className="h-3 w-3 text-emerald-400 shrink-0 mt-0.5" />
                    <span className="text-[11px] text-emerald-400/80">{err.resolution}</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
