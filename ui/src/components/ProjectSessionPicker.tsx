import { X, FolderOpen, Plus, ArrowRight } from "lucide-react";
import type { SessionListItem } from "@/api/types";
import { cn } from "@/lib/utils";

interface ProjectSessionPickerProps {
  projectPath: string;
  sessions: SessionListItem[];
  onResume: (sessionId: string) => void;
  onNew: () => void;
  onClose: () => void;
}

function formatDate(ts: number): string {
  const d = new Date(ts * 1000);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffHr = diffMs / (1000 * 60 * 60);
  if (diffHr < 1) return "just now";
  if (diffHr < 24) return `${Math.floor(diffHr)}h ago`;
  if (diffHr < 48) return "yesterday";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function statusLabel(status: string): { text: string; cls: string } {
  switch (status) {
    case "active": return { text: "Active", cls: "text-emerald-400" };
    case "completed": return { text: "Completed", cls: "text-zinc-400" };
    case "error": return { text: "Error", cls: "text-red-400" };
    default: return { text: status, cls: "text-zinc-500" };
  }
}

export function ProjectSessionPicker({
  projectPath,
  sessions,
  onResume,
  onNew,
  onClose,
}: ProjectSessionPickerProps) {
  const folderName = projectPath.split("/").pop() || projectPath;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-xl border border-zinc-800 bg-zinc-950 shadow-2xl">
        <div className="flex items-center justify-between border-b border-zinc-800 px-5 py-4">
          <div className="flex items-center gap-2.5 min-w-0">
            <FolderOpen className="h-4 w-4 text-emerald-400 shrink-0" />
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-zinc-100 truncate">{folderName}</h2>
              <p className="text-[11px] text-zinc-500 truncate">{projectPath}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300 transition-colors"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="px-5 py-3">
          <p className="text-xs text-zinc-500 mb-3">
            {sessions.length} existing session{sessions.length !== 1 ? "s" : ""} for this project
          </p>

          <div className="space-y-1.5 max-h-64 overflow-y-auto">
            {sessions.map((s) => {
              const st = statusLabel(s.status);
              return (
                <button
                  key={s.session_id}
                  onClick={() => onResume(s.session_id)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors",
                    "bg-zinc-900/50 hover:bg-zinc-800/80 border border-zinc-800/50 hover:border-zinc-700/50"
                  )}
                >
                  <div className="flex-1 min-w-0">
                    <span className="block text-xs font-medium text-zinc-200 truncate">
                      {s.title || `Session ${s.session_id.slice(0, 8)}`}
                    </span>
                    <span className="block text-[10px] text-zinc-500 mt-0.5">
                      {formatDate(s.updated_at)}
                      <span className={cn("ml-2", st.cls)}>{st.text}</span>
                    </span>
                  </div>
                  <ArrowRight className="h-3.5 w-3.5 text-zinc-600 shrink-0" />
                </button>
              );
            })}
          </div>
        </div>

        <div className="border-t border-zinc-800 px-5 py-3">
          <button
            onClick={onNew}
            className={cn(
              "flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-xs font-medium transition-colors",
              "bg-emerald-600/20 text-emerald-400 hover:bg-emerald-600/30 border border-emerald-600/30"
            )}
          >
            <Plus className="h-3.5 w-3.5" />
            Start New Session
          </button>
        </div>
      </div>
    </div>
  );
}
