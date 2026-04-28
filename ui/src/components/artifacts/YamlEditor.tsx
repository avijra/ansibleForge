import { Copy, Check, Download } from "lucide-react";
import { useState } from "react";

interface YamlEditorProps {
  filename: string;
  content: string;
}

export function YamlEditor({ filename, content }: YamlEditorProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    const blob = new Blob([content], { type: "text/yaml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="rounded-md border border-zinc-800 overflow-hidden">
      <div className="flex items-center justify-between bg-zinc-900 px-3 py-1.5 border-b border-zinc-800">
        <span className="text-xs font-mono text-zinc-400">{filename}</span>
        <div className="flex items-center gap-1">
          <button
            onClick={handleCopy}
            className="rounded p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300 transition-colors"
            title="Copy"
          >
            {copied ? (
              <Check className="h-3.5 w-3.5 text-emerald-400" />
            ) : (
              <Copy className="h-3.5 w-3.5" />
            )}
          </button>
          <button
            onClick={handleDownload}
            className="rounded p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-300 transition-colors"
            title="Download"
          >
            <Download className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      <pre className="p-3 text-xs font-mono text-zinc-300 bg-zinc-950 overflow-x-auto whitespace-pre leading-relaxed">
        {highlightYaml(content)}
      </pre>
    </div>
  );
}

function highlightYaml(yaml: string): React.ReactNode {
  return yaml.split("\n").map((line, i) => {
    let className = "text-zinc-300";
    if (line.trimStart().startsWith("#")) {
      className = "text-zinc-600 italic";
    } else if (line.trimStart().startsWith("- ")) {
      className = "text-cyan-400/80";
    } else if (line.includes(":") && !line.trimStart().startsWith("-")) {
      const colonIdx = line.indexOf(":");
      return (
        <div key={i}>
          <span className="text-blue-400/80">{line.slice(0, colonIdx)}</span>
          <span className="text-zinc-500">:</span>
          <span className="text-zinc-300">{line.slice(colonIdx + 1)}</span>
        </div>
      );
    } else if (line.trim() === "---") {
      className = "text-zinc-600";
    }
    return (
      <div key={i} className={className}>
        {line || "\u00A0"}
      </div>
    );
  });
}
