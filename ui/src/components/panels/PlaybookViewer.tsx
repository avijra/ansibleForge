import { useState } from "react";
import { FileCode2, ChevronDown, ChevronRight, Copy, Check, Download } from "lucide-react";
import { cn } from "@/lib/utils";

interface PlaybookViewerProps {
  playbooks: Record<string, string>;
}

export function PlaybookViewer({ playbooks }: PlaybookViewerProps) {
  const entries = Object.entries(playbooks);

  if (entries.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 p-6 text-center">
        <div className="rounded-xl bg-zinc-900/50 p-4 ring-1 ring-zinc-800">
          <FileCode2 className="h-8 w-8 text-zinc-600" />
        </div>
        <div>
          <p className="text-xs text-zinc-500">No playbooks generated yet</p>
          <p className="mt-1 text-[11px] text-zinc-600">
            Ask the agent to generate or deploy something to see playbooks here
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="divide-y divide-zinc-800/50">
      {entries.map(([name, content]) => (
        <PlaybookFile key={name} filename={name} content={content} defaultOpen={entries.length === 1} />
      ))}
    </div>
  );
}

function PlaybookFile({
  filename,
  content,
  defaultOpen,
}: {
  filename: string;
  content: string;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [copied, setCopied] = useState(false);

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    await navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = (e: React.MouseEvent) => {
    e.stopPropagation();
    const blob = new Blob([content], { type: "text/yaml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  const lineCount = content.split("\n").length;

  return (
    <div className="min-w-0">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 w-full min-w-0 px-4 py-3 text-left hover:bg-zinc-900/50 transition-colors"
      >
        {open
          ? <ChevronDown className="h-3.5 w-3.5 text-zinc-500 shrink-0" />
          : <ChevronRight className="h-3.5 w-3.5 text-zinc-500 shrink-0" />}
        <FileCode2 className="h-3.5 w-3.5 text-blue-400/70 shrink-0" />
        <span className="text-xs font-mono text-zinc-300 truncate flex-1">{filename}</span>
        <span className="text-[10px] font-mono text-zinc-600 shrink-0">{lineCount} lines</span>
        <button
          onClick={handleCopy}
          className="rounded p-1 text-zinc-600 hover:bg-zinc-800 hover:text-zinc-300 transition-colors shrink-0"
          title="Copy"
        >
          {copied
            ? <Check className="h-3 w-3 text-emerald-400" />
            : <Copy className="h-3 w-3" />}
        </button>
        <button
          onClick={handleDownload}
          className="rounded p-1 text-zinc-600 hover:bg-zinc-800 hover:text-zinc-300 transition-colors shrink-0"
          title="Download"
        >
          <Download className="h-3 w-3" />
        </button>
      </button>

      {open && (
        <div className="px-4 pb-4 animate-slide-in">
          <div className="rounded-md border border-zinc-800 overflow-hidden">
            <pre className="p-3 text-[11px] font-mono bg-zinc-950 overflow-x-auto whitespace-pre leading-relaxed">
              {highlightYaml(content)}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

function highlightYaml(yaml: string): React.ReactNode {
  return yaml.split("\n").map((line, i) => {
    if (line.trimStart().startsWith("#")) {
      return (
        <div key={i} className="text-zinc-600 italic">{line || "\u00A0"}</div>
      );
    }
    if (line.trim() === "---") {
      return (
        <div key={i} className="text-zinc-600">{line}</div>
      );
    }
    if (line.includes(":") && !line.trimStart().startsWith("-")) {
      const colonIdx = line.indexOf(":");
      return (
        <div key={i}>
          <span className="text-blue-400/80">{line.slice(0, colonIdx)}</span>
          <span className="text-zinc-500">:</span>
          <span className="text-zinc-300">{line.slice(colonIdx + 1)}</span>
        </div>
      );
    }
    if (line.trimStart().startsWith("- ")) {
      return (
        <div key={i} className="text-cyan-400/80">{line || "\u00A0"}</div>
      );
    }
    return (
      <div key={i} className="text-zinc-300">{line || "\u00A0"}</div>
    );
  });
}
