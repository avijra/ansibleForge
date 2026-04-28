import { cn } from "@/lib/utils";

const ANSI_COLORS: Record<string, string> = {
  "30": "text-zinc-500",
  "31": "text-red-400",
  "32": "text-emerald-400",
  "33": "text-amber-400",
  "34": "text-blue-400",
  "35": "text-violet-400",
  "36": "text-cyan-400",
  "37": "text-zinc-200",
  "90": "text-zinc-500",
  "91": "text-red-300",
  "92": "text-emerald-300",
  "93": "text-amber-300",
  "94": "text-blue-300",
  "95": "text-violet-300",
  "96": "text-cyan-300",
  "97": "text-white",
};

interface AnsiSpan {
  text: string;
  className: string;
}

function parseAnsi(input: string): AnsiSpan[] {
  const spans: AnsiSpan[] = [];
  const regex = /\x1b\[([0-9;]*)m/g;
  let lastIndex = 0;
  let currentClass = "text-zinc-300";

  let match;
  while ((match = regex.exec(input)) !== null) {
    if (match.index > lastIndex) {
      spans.push({ text: input.slice(lastIndex, match.index), className: currentClass });
    }
    const codes = match[1].split(";");
    for (const code of codes) {
      if (code === "0" || code === "") {
        currentClass = "text-zinc-300";
      } else if (code === "1") {
        currentClass = currentClass + " font-bold";
      } else if (ANSI_COLORS[code]) {
        currentClass = ANSI_COLORS[code];
      }
    }
    lastIndex = regex.lastIndex;
  }
  if (lastIndex < input.length) {
    spans.push({ text: input.slice(lastIndex), className: currentClass });
  }
  return spans;
}

interface TerminalOutputProps {
  content: string;
  maxHeight?: string;
  className?: string;
}

export function TerminalOutput({
  content,
  maxHeight = "max-h-64",
  className,
}: TerminalOutputProps) {
  const hasAnsi = content.includes("\x1b[");
  const lines = content.split("\n");

  return (
    <pre
      className={cn(
        "rounded-md bg-zinc-950 border border-zinc-800 p-2.5 text-[11px] font-mono leading-relaxed overflow-y-auto overflow-x-auto whitespace-pre-wrap",
        maxHeight,
        className
      )}
    >
      {hasAnsi
        ? lines.map((line, i) => (
            <span key={i}>
              {parseAnsi(line).map((span, j) => (
                <span key={j} className={span.className}>{span.text}</span>
              ))}
              {i < lines.length - 1 && "\n"}
            </span>
          ))
        : <span className="text-zinc-300">{content}</span>
      }
    </pre>
  );
}
