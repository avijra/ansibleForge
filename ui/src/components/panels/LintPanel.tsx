import { useCallback, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Info,
  RefreshCw,
  Shield,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface LintViolation {
  rule: string;
  severity: string;
  message: string;
  filename: string;
  line: number;
}

interface LintPanelProps {
  sessionId: string | null;
  onOpenFile: (path: string, line: number) => void;
}

function severityIcon(severity: string) {
  switch (severity) {
    case "error":
    case "very-high":
      return <XCircle className="h-3.5 w-3.5 text-red-400 shrink-0" />;
    case "warning":
    case "high":
    case "medium":
      return <AlertTriangle className="h-3.5 w-3.5 text-amber-400 shrink-0" />;
    default:
      return <Info className="h-3.5 w-3.5 text-blue-400 shrink-0" />;
  }
}

export function LintPanel({ sessionId, onOpenFile }: LintPanelProps) {
  const [violations, setViolations] = useState<LintViolation[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasRun, setHasRun] = useState(false);

  const runLint = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      const apiKey = import.meta.env.VITE_API_KEY;
      if (apiKey) headers["X-API-Key"] = apiKey;

      const res = await fetch(`/api/v1/lint/${sessionId}`, { headers });
      if (res.ok) {
        const data = await res.json();
        setViolations(data.violations || []);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
      setHasRun(true);
    }
  }, [sessionId]);

  const grouped = violations.reduce<Record<string, LintViolation[]>>((acc, v) => {
    (acc[v.filename] ??= []).push(v);
    return acc;
  }, {});

  const errorCount = violations.filter((v) => v.severity === "error" || v.severity === "very-high").length;
  const warnCount = violations.length - errorCount;

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-800 shrink-0">
        <Shield className="h-3.5 w-3.5 text-zinc-500" />
        <span className="text-xs font-medium text-zinc-400 flex-1">Problems</span>
        {hasRun && violations.length > 0 && (
          <div className="flex items-center gap-2 text-[10px]">
            {errorCount > 0 && (
              <span className="flex items-center gap-1 text-red-400">
                <XCircle className="h-3 w-3" /> {errorCount}
              </span>
            )}
            {warnCount > 0 && (
              <span className="flex items-center gap-1 text-amber-400">
                <AlertTriangle className="h-3 w-3" /> {warnCount}
              </span>
            )}
          </div>
        )}
        <button
          onClick={runLint}
          disabled={loading || !sessionId}
          className={cn(
            "flex items-center gap-1 rounded px-2 py-1 text-[10px] transition-colors",
            loading
              ? "text-zinc-600"
              : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
          )}
        >
          <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
          {loading ? "Scanning..." : "Run Lint"}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {!hasRun && (
          <div className="flex flex-col items-center justify-center h-full gap-2 text-center px-6">
            <Shield className="h-6 w-6 text-zinc-700" />
            <p className="text-xs text-zinc-500">Click "Run Lint" to check your playbooks</p>
          </div>
        )}

        {hasRun && violations.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-2 text-center px-6">
            <CheckCircle2 className="h-6 w-6 text-emerald-500/60" />
            <p className="text-xs text-zinc-400">No issues found</p>
          </div>
        )}

        {Object.entries(grouped).map(([filename, items]) => (
          <div key={filename} className="border-b border-zinc-800/50">
            <div className="px-3 py-1.5 text-[11px] font-mono text-zinc-400 bg-zinc-900/30">
              {filename}
              <span className="ml-2 text-zinc-600">{items.length}</span>
            </div>
            {items.map((v, i) => (
              <button
                key={i}
                onClick={() => onOpenFile(v.filename, v.line)}
                className="flex items-start gap-2 w-full px-3 py-1.5 text-left hover:bg-zinc-900/50 transition-colors"
              >
                {severityIcon(v.severity)}
                <div className="flex-1 min-w-0">
                  <span className="text-[11px] text-zinc-300 block truncate">{v.message}</span>
                  <span className="text-[10px] text-zinc-600">
                    {v.rule} · line {v.line}
                  </span>
                </div>
              </button>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
