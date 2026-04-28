import { cn } from "@/lib/utils";

interface JsonBlockProps {
  data: unknown;
  maxLines?: number;
  className?: string;
}

export function JsonBlock({ data, maxLines = 20, className }: JsonBlockProps) {
  const text = typeof data === "string" ? data : JSON.stringify(data, null, 2);
  const lines = text.split("\n");
  const truncated = lines.length > maxLines;
  const display = truncated ? lines.slice(0, maxLines).join("\n") + "\n…" : text;

  return (
    <pre
      className={cn(
        "rounded-md bg-zinc-900/80 border border-zinc-800 p-3 text-xs font-mono text-zinc-300 overflow-x-auto",
        className
      )}
    >
      {display}
    </pre>
  );
}
