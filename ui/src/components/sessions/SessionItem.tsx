import { MessageSquare } from "lucide-react";
import type { Session } from "@/api/types";
import { cn } from "@/lib/utils";
import { StatusBadge } from "@/components/common/StatusBadge";

interface SessionItemProps {
  session: Session;
  isActive: boolean;
  onClick: () => void;
}

export function SessionItem({ session, isActive, onClick }: SessionItemProps) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors",
        isActive
          ? "bg-zinc-800 text-zinc-100"
          : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-300"
      )}
    >
      <MessageSquare className="h-3.5 w-3.5 shrink-0" />
      <span className="flex-1 truncate font-mono">{session.id.slice(0, 12)}</span>
      <StatusBadge status={session.status} className="text-[10px] px-1 py-0" />
    </button>
  );
}
