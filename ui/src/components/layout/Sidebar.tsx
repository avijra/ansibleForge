import { useState } from "react";
import { Plus, MessageSquare, Trash2, Terminal, Server, GitBranch, Brain } from "lucide-react";
import type { Session } from "@/api/types";
import { cn } from "@/lib/utils";

interface SidebarProps {
  sessions: Session[];
  activeId: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
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
}: {
  session: Session;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  const [showDelete, setShowDelete] = useState(false);
  const label = session.title || session.id.slice(0, 12);

  return (
    <div
      className="relative group"
      onMouseEnter={() => setShowDelete(true)}
      onMouseLeave={() => setShowDelete(false)}
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
          <span className={cn("block truncate", session.title ? "font-medium" : "font-mono")}>
            {label}
          </span>
          <span className="block text-[10px] text-zinc-600 mt-0.5">
            {timeAgo(session.createdAt)}
          </span>
        </div>
      </button>
      {showDelete && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-zinc-600 hover:text-red-400 hover:bg-zinc-800 transition-colors"
          aria-label="Delete session"
          title="Delete session"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      )}
    </div>
  );
}

export function Sidebar({ sessions, activeId, onSelect, onNew, onDelete }: SidebarProps) {
  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-zinc-800 bg-zinc-950">
      {/* Logo area */}
      <div className="px-3 py-3 border-b border-zinc-800/50">
        <div className="flex items-center gap-2">
          <Terminal className="h-4 w-4 text-teal-400" />
          <span className="text-xs font-semibold tracking-tight text-zinc-200">
            AnsibleForge
          </span>
        </div>
      </div>

      {/* Sessions header */}
      <div className="flex items-center justify-between px-3 py-2.5">
        <span className="text-[10px] font-medium uppercase tracking-wider text-zinc-600">
          Sessions ({sessions.length})
        </span>
        <button
          onClick={onNew}
          className="rounded-md p-1 text-zinc-400 hover:bg-zinc-800 hover:text-teal-400 transition-colors"
          title="New session"
          aria-label="New session"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto px-2 space-y-0.5">
        {sessions.map((s) => (
          <SessionRow
            key={s.id}
            session={s}
            isActive={s.id === activeId}
            onSelect={() => onSelect(s.id)}
            onDelete={() => onDelete(s.id)}
          />
        ))}
      </div>

      {/* Nav links */}
      <div className="border-t border-zinc-800 p-2 space-y-0.5">
        <span className="block px-2 py-1 text-[10px] font-medium uppercase tracking-wider text-zinc-600">
          Views
        </span>
        <NavLink icon={Server} label="Hosts" />
        <NavLink icon={GitBranch} label="Runs" />
        <NavLink icon={Brain} label="Knowledge" />
      </div>
    </aside>
  );
}

function NavLink({ icon: Icon, label }: { icon: typeof Server; label: string }) {
  return (
    <button className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs text-zinc-500 hover:bg-zinc-900 hover:text-zinc-300 transition-colors">
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}
