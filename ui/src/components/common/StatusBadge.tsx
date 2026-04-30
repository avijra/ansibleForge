import { cn } from "@/lib/utils";

interface StatusBadgeProps {
  status: string;
  className?: string;
}

const statusConfig: Record<string, { bg: string; text: string; dot: string }> = {
  success: { bg: "bg-zinc-800/40", text: "text-zinc-400", dot: "bg-zinc-400" },
  error: { bg: "bg-zinc-800/40", text: "text-zinc-400", dot: "bg-zinc-500" },
  needs_approval: { bg: "bg-zinc-800/40", text: "text-zinc-300", dot: "bg-zinc-400" },
  awaiting_approval: { bg: "bg-zinc-800/40", text: "text-zinc-300", dot: "bg-zinc-400" },
  active: { bg: "bg-zinc-800/40", text: "text-zinc-400", dot: "bg-zinc-400" },
  completed: { bg: "bg-zinc-800/40", text: "text-zinc-400", dot: "bg-zinc-500" },
  rejected: { bg: "bg-zinc-800/40", text: "text-zinc-500", dot: "bg-zinc-600" },
  healthy: { bg: "bg-zinc-800/40", text: "text-zinc-400", dot: "bg-zinc-400" },
};

const fallback = { bg: "bg-zinc-500/10", text: "text-zinc-400", dot: "bg-zinc-400" };

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const cfg = statusConfig[status] || fallback;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium",
        cfg.bg,
        cfg.text,
        className
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", cfg.dot)} aria-hidden="true" />
      {status.replace(/_/g, " ")}
    </span>
  );
}
