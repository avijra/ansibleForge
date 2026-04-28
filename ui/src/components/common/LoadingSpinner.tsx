import { cn } from "@/lib/utils";

export function LoadingSpinner({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-1.5", className)}>
      <span className="h-1.5 w-1.5 rounded-full bg-teal-400 animate-pulse-dot" />
      <span className="h-1.5 w-1.5 rounded-full bg-teal-400 animate-pulse-dot [animation-delay:300ms]" />
      <span className="h-1.5 w-1.5 rounded-full bg-teal-400 animate-pulse-dot [animation-delay:600ms]" />
    </div>
  );
}
