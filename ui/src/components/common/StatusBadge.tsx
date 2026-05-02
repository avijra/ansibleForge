import { cn } from "@/lib/utils";

interface StatusBadgeProps {
  status: string;
  className?: string;
  title?: string;
}

const statusConfig: Record<string, { bg: string; text: string; dot: string }> = {
  success: { bg: "bg-emerald-950/30", text: "text-emerald-400", dot: "bg-emerald-400" },
  error: { bg: "bg-red-950/30", text: "text-red-400", dot: "bg-red-400" },
  needs_approval: { bg: "bg-amber-950/30", text: "text-amber-400", dot: "bg-amber-400 animate-pulse" },
  awaiting_approval: { bg: "bg-amber-950/30", text: "text-amber-400", dot: "bg-amber-400 animate-pulse" },
  awaiting_secret: { bg: "bg-amber-950/30", text: "text-amber-400", dot: "bg-amber-400 animate-pulse" },
  active: { bg: "bg-blue-950/30", text: "text-blue-400", dot: "bg-blue-400" },
  completed: { bg: "bg-zinc-800/40", text: "text-zinc-400", dot: "bg-zinc-500" },
  rejected: { bg: "bg-red-950/20", text: "text-red-500/70", dot: "bg-red-600" },
  healthy: { bg: "bg-emerald-950/30", text: "text-emerald-400", dot: "bg-emerald-400" },
  degraded: { bg: "bg-amber-950/30", text: "text-amber-400", dot: "bg-amber-400 animate-pulse" },
  unknown: { bg: "bg-zinc-800/40", text: "text-zinc-500", dot: "bg-zinc-500" },
};

const fallback = { bg: "bg-zinc-800/40", text: "text-zinc-500", dot: "bg-zinc-500" };

export function StatusBadge({ status, className, title }: StatusBadgeProps) {
  const cfg = statusConfig[status] || fallback;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium",
        cfg.bg,
        cfg.text,
        className
      )}
      title={title}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", cfg.dot)} aria-hidden="true" />
      {status.replace(/_/g, " ")}
    </span>
  );
}
