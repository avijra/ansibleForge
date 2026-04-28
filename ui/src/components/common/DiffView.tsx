import { cn } from "@/lib/utils";

interface DiffViewProps {
  content: string;
  maxHeight?: string;
}

export function DiffView({ content, maxHeight = "max-h-64" }: DiffViewProps) {
  const lines = content.split("\n");

  return (
    <pre
      className={cn(
        "rounded-md bg-zinc-950 border border-zinc-800 overflow-y-auto overflow-x-auto text-[11px] font-mono leading-relaxed",
        maxHeight
      )}
    >
      {lines.map((line, i) => {
        const isAdd = line.startsWith("+") && !line.startsWith("+++");
        const isDel = line.startsWith("-") && !line.startsWith("---");
        const isHeader = line.startsWith("+++") || line.startsWith("---");
        const isHunk = line.startsWith("@@");

        return (
          <div
            key={i}
            className={cn(
              "px-2.5 py-px",
              isAdd && "bg-emerald-500/8 text-emerald-400",
              isDel && "bg-red-500/8 text-red-400",
              isHeader && "text-zinc-500 font-bold",
              isHunk && "text-cyan-400/70 bg-cyan-500/5",
              !isAdd && !isDel && !isHeader && !isHunk && "text-zinc-500"
            )}
          >
            <span className="select-none inline-block w-6 text-right mr-2 text-zinc-700 text-[10px]">
              {i + 1}
            </span>
            {line}
          </div>
        );
      })}
    </pre>
  );
}
