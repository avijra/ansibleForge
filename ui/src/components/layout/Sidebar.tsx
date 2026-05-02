import { useState } from "react";
import { Trash2, Server, GitBranch, Brain, Trash, FolderOpen, RotateCcw } from "lucide-react";
import type { Session } from "@/api/types";
import { cn } from "@/lib/utils";

export type SidebarView = "chat" | "hosts" | "runs" | "knowledge";

interface SidebarProps {
  sessions: Session[];
  activeId: string | null;
  activeView: SidebarView;
  onSelect: (id: string) => void;
  onOpenFolder: () => void;
  onDelete: (id: string) => void;
  onReset: (id: string) => void;
  onClearAll?: () => void;
  onViewChange: (view: SidebarView) => void;
}

function timeAgo(ts: number): string {
  const diff = Date.now() - ts;
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return "now";
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h`;
  return `${Math.floor(hr / 24)}d`;
}

function statusDot(status: Session["status"]): string {
  switch (status) {
    case "active": return "bg-emerald-400";
    case "completed": return "bg-zinc-500";
    case "awaiting_approval": return "bg-amber-400 animate-pulse-dot";
    case "awaiting_secret": return "bg-amber-400 animate-pulse-dot";
    case "error": return "bg-red-400";
    case "rejected": return "bg-zinc-600";
    default: return "bg-zinc-600";
  }
}

function SessionRow({
  session,
  isActive,
  onSelect,
  onDelete,
  onReset,
}: {
  session: Session;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
  onReset: () => void;
}) {
  const [showActions, setShowActions] = useState(false);
  const projectName = session.projectPath?.split("/").pop();
  const label = session.title || projectName || session.id.slice(0, 12);

  return (
    <div
      className="relative group"
      onMouseEnter={() => setShowActions(true)}
      onMouseLeave={() => setShowActions(false)}
    >
      <button
        onClick={onSelect}
        className={cn(
          "flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-xs transition-colors",
          isActive
            ? "bg-zinc-800/80 text-zinc-100"
            : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-300"
        )}
      >
        <span className={cn("h-2 w-2 rounded-full shrink-0", statusDot(session.status))} />
        <div className="flex-1 min-w-0">
          <span className={cn("block truncate", (session.title || projectName) ? "font-medium" : "font-mono")}>
            {label}
          </span>
          <span className="block text-[10px] text-zinc-600 mt-0.5">
            {timeAgo(session.createdAt)}
            {projectName && (
              <span className="ml-1 text-zinc-700">· {projectName}</span>
            )}
          </span>
        </div>
      </button>
      {showActions && (
        <div className="absolute right-1 top-1/2 -translate-y-1/2 flex items-center gap-0.5">
          <button
            onClick={(e) => {
              e.stopPropagation();
              onReset();
            }}
            className="rounded p-1 text-zinc-600 hover:text-amber-400 hover:bg-zinc-800 transition-colors"
            aria-label="Reset session"
            title="Reset session"
          >
            <RotateCcw className="h-3 w-3" />
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            className="rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-zinc-800 transition-colors"
            aria-label="Delete session"
            title="Delete session"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        </div>
      )}
    </div>
  );
}

export function Sidebar({ sessions, activeId, activeView, onSelect, onOpenFolder, onDelete, onReset, onClearAll, onViewChange }: SidebarProps) {
  const [confirmClear, setConfirmClear] = useState(false);

  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-zinc-800 bg-zinc-950">
      {/* Logo area */}
      <div className="px-3 py-3 border-b border-zinc-800/50">
        <div className="flex items-center gap-2">
          <svg width="18" height="18" viewBox="0 0 120 120" fill="none" className="shrink-0">
            <path d="M20 52 L42 46 L42 74 L20 68 Z" fill="#9CA3AF" opacity="0.85"/>
            <path d="M42 44 L72 38 L72 82 L42 76 Z" fill="#9CA3AF"/>
            <path d="M72 50 Q85 48 98 44" stroke="#10B981" strokeWidth="3" strokeLinecap="round" opacity="0.8"/>
            <path d="M72 60 Q90 60 108 60" stroke="#10B981" strokeWidth="3" strokeLinecap="round" opacity="0.9"/>
            <path d="M72 70 Q85 72 98 76" stroke="#10B981" strokeWidth="3" strokeLinecap="round" opacity="0.8"/>
            <circle cx="108" cy="60" r="4" fill="#10B981" opacity="0.85"/>
          </svg>
          <span className="text-xs font-semibold tracking-widest uppercase text-zinc-200">
            Tuyere
          </span>
        </div>
      </div>

      {/* Sessions header */}
      <div className="flex items-center justify-between px-3 py-2.5">
        <span className="text-[10px] font-medium uppercase tracking-wider text-zinc-600">
          Sessions ({sessions.length})
        </span>
        <div className="flex items-center gap-0.5">
          {sessions.length > 1 && onClearAll && (
            confirmClear ? (
              <div className="flex items-center gap-1 mr-1">
                <button
                  onClick={() => { onClearAll(); setConfirmClear(false); }}
                  className="rounded px-1.5 py-0.5 text-[10px] font-medium text-red-400 bg-red-950/40 hover:bg-red-900/40 transition-colors"
                >
                  Confirm
                </button>
                <button
                  onClick={() => setConfirmClear(false)}
                  className="rounded px-1.5 py-0.5 text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                onClick={() => setConfirmClear(true)}
                className="rounded-md p-1 text-zinc-600 hover:bg-zinc-800 hover:text-red-400 transition-colors"
                title="Clear all sessions"
                aria-label="Clear all sessions"
              >
                <Trash className="h-3 w-3" />
              </button>
            )
          )}
          <button
            onClick={onOpenFolder}
            className="rounded-md p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200 transition-colors"
            title="Open project folder"
            aria-label="Open project folder"
          >
            <FolderOpen className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto px-2 space-y-0.5">
        {sessions.length === 0 ? (
          <div className="px-2 py-6 text-center">
            <p className="text-[11px] text-zinc-600">No sessions yet</p>
            <button
              onClick={onOpenFolder}
              className="mt-2 inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs text-zinc-400 hover:text-zinc-200 bg-zinc-900 hover:bg-zinc-800 transition-colors"
            >
              <FolderOpen className="h-3.5 w-3.5" />
              Open Folder
            </button>
          </div>
        ) : (
          sessions.map((s) => (
            <SessionRow
              key={s.id}
              session={s}
              isActive={s.id === activeId}
              onSelect={() => onSelect(s.id)}
              onDelete={() => onDelete(s.id)}
              onReset={() => onReset(s.id)}
            />
          ))
        )}
      </div>

      <div className="border-t border-zinc-800 p-2 space-y-0.5">
        <span className="block px-2 py-1 text-[10px] font-medium uppercase tracking-wider text-zinc-600">
          Views
        </span>
        <NavLink icon={Server} label="Hosts" active={activeView === "hosts"} onClick={() => onViewChange("hosts")} />
        <NavLink icon={GitBranch} label="Runs" active={activeView === "runs"} onClick={() => onViewChange("runs")} />
        <NavLink icon={Brain} label="Knowledge" active={activeView === "knowledge"} onClick={() => onViewChange("knowledge")} />
      </div>
    </aside>
  );
}

function NavLink({ icon: Icon, label, active, onClick }: { icon: typeof Server; label: string; active?: boolean; onClick?: () => void }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs transition-colors",
        active
          ? "bg-zinc-800/80 text-zinc-100"
          : "text-zinc-500 hover:bg-zinc-900 hover:text-zinc-300"
      )}
      title={label}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}
