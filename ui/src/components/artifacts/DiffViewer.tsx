import type { AgentEvent } from "@/api/types";
import { cn } from "@/lib/utils";

interface DiffViewerProps {
  events: AgentEvent[];
}

export function DiffViewer({ events }: DiffViewerProps) {
  const diffs: { host: string; task: string; diff: string }[] = [];

  for (const evt of events) {
    if (evt.event !== "tool_result") continue;
    const evtEvents = (evt.data.events as Array<Record<string, unknown>>) || [];
    for (const e of evtEvents) {
      const result = e.result as Record<string, unknown> | undefined;
      if (result?.diff) {
        diffs.push({
          host: (e.host as string) || "",
          task: (e.task as string) || "",
          diff: formatDiff(result.diff),
        });
      }
    }
  }

  if (diffs.length === 0) {
    return (
      <p className="py-6 text-center text-xs text-zinc-600">
        No diffs available. Run a playbook in check mode to see changes.
      </p>
    );
  }

  return (
    <div className="p-2 space-y-2">
      {diffs.map((d, i) => (
        <div key={i} className="rounded-md border border-zinc-800 overflow-hidden">
          <div className="bg-zinc-900 px-3 py-1.5 border-b border-zinc-800 text-xs text-zinc-400">
            <span className="font-mono">{d.host}</span>
            <span className="mx-2 text-zinc-700">/</span>
            <span>{d.task}</span>
          </div>
          <pre className="p-3 text-xs font-mono leading-relaxed overflow-x-auto">
            {d.diff.split("\n").map((line, j) => (
              <div
                key={j}
                className={cn(
                  line.startsWith("+")
                    ? "text-emerald-400 bg-emerald-400/5"
                    : line.startsWith("-")
                      ? "text-red-400 bg-red-400/5"
                      : line.startsWith("@@")
                        ? "text-cyan-400"
                        : "text-zinc-500"
                )}
              >
                {line || "\u00A0"}
              </div>
            ))}
          </pre>
        </div>
      ))}
    </div>
  );
}

function formatDiff(diff: unknown): string {
  if (typeof diff === "string") return diff;
  if (typeof diff === "object" && diff !== null) {
    const d = diff as Record<string, unknown>;
    const before = String(d.before || "");
    const after = String(d.after || "");
    return `--- before\n${before}\n+++ after\n${after}`;
  }
  return JSON.stringify(diff, null, 2);
}
