import { cn } from "@/lib/utils";

interface TuyereLogoProps {
  className?: string;
  animate?: boolean;
  size?: number;
}

export function TuyereLogo({ className, animate = false, size = 20 }: TuyereLogoProps) {
  return (
    <svg
      viewBox="0 0 32 32"
      width={size}
      height={size}
      className={cn(className)}
      aria-hidden="true"
    >
      {/* Nozzle body */}
      <path
        d="M6 12 L14 10 L14 22 L6 20 Z"
        fill="currentColor"
        opacity={0.6}
      />
      <path
        d="M14 9 L18 8 L18 24 L14 23 Z"
        fill="currentColor"
        opacity={0.8}
      />

      {/* Fire streams */}
      <ellipse cx="22" cy="13" rx="3.5" ry="2" className={cn(animate && "animate-fire-1")} fill="#10b981" opacity={0.9} />
      <ellipse cx="24" cy="16" rx="4" ry="2.5" className={cn(animate && "animate-fire-2")} fill="#34d399" opacity={0.7} />
      <ellipse cx="22" cy="19" rx="3.5" ry="2" className={cn(animate && "animate-fire-3")} fill="#10b981" opacity={0.9} />

      {/* Spark particles */}
      <circle cx="27" cy="12" r="1" className={cn(animate && "animate-spark-1")} fill="#6ee7b7" opacity={0.8} />
      <circle cx="28" cy="16" r="1.2" className={cn(animate && "animate-spark-2")} fill="#a7f3d0" opacity={0.6} />
      <circle cx="27" cy="20" r="1" className={cn(animate && "animate-spark-3")} fill="#6ee7b7" opacity={0.8} />
    </svg>
  );
}

export function TuyereThinkingIndicator({ message }: { message?: string }) {
  return (
    <div className="flex items-center gap-2.5 py-3" role="status" aria-live="polite">
      <TuyereLogo animate size={22} className="text-emerald-600 shrink-0" />
      <span className="text-xs text-zinc-500 animate-pulse">{message || "Thinking..."}</span>
      <span className="sr-only">Working</span>
    </div>
  );
}
