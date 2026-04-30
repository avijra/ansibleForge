import { cn } from "@/lib/utils";

export function LoadingSpinner({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-1.5", className)} role="status" aria-live="polite">
      <span className="h-1 w-1 rounded-full bg-zinc-600 animate-pulse-dot" aria-hidden="true" />
      <span className="h-1 w-1 rounded-full bg-zinc-600 animate-pulse-dot [animation-delay:300ms]" aria-hidden="true" />
      <span className="h-1 w-1 rounded-full bg-zinc-600 animate-pulse-dot [animation-delay:600ms]" aria-hidden="true" />
      <span className="sr-only">Loading</span>
    </div>
  );
}
