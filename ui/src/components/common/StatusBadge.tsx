import { cn } from "@/lib/utils";

interface StatusBadgeProps {
  status: string;
  className?: string;
}

const statusConfig: Record<string, { bg: string; text: string; dot: string }> = {
  success: { bg: "bg-emerald-500/10", text: "text-emerald-400", dot: "bg-emerald-400" },
  error: { bg: "bg-red-500/10", text: "text-red-400", dot: "bg-red-400" },
  needs_approval: { bg: "bg-amber-500/10", text: "text-amber-400", dot: "bg-amber-400" },
  awaiting_approval: { bg: "bg-amber-500/10", text: "text-amber-400", dot: "bg-amber-400" },
  active: { bg: "bg-teal-500/10", text: "text-teal-400", dot: "bg-teal-400" },
  completed: { bg: "bg-emerald-500/10", text: "text-emerald-400", dot: "bg-emerald-400" },
  rejected: { bg: "bg-zinc-500/10", text: "text-zinc-400", dot: "bg-zinc-400" },
  healthy: { bg: "bg-emerald-500/10", text: "text-emerald-400", dot: "bg-emerald-400" },
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
      <span className={cn("h-1.5 w-1.5 rounded-full", cfg.dot)} />
      {status.replace(/_/g, " ")}
    </span>
  );
}
