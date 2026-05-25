import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import mermaid from "mermaid";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

mermaid.initialize({
  startOnLoad: false,
  theme: "dark",
  themeVariables: {
    darkMode: true,
    background: "#18181b",
    primaryColor: "#3f3f46",
    primaryTextColor: "#e4e4e7",
    primaryBorderColor: "#52525b",
    lineColor: "#71717a",
    secondaryColor: "#27272a",
    tertiaryColor: "#1e1e22",
    fontFamily: "ui-monospace, monospace",
    fontSize: "12px",
  },
  flowchart: { curve: "basis", padding: 12 },
  securityLevel: "strict",
});

function MermaidDiagram({ code }: { code: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const uniqueId = useId().replace(/:/g, "_");

  const render = useCallback(async () => {
    if (!containerRef.current) return;
    try {
      const { svg } = await mermaid.render(`mermaid_${uniqueId}`, code);
      if (containerRef.current) {
        containerRef.current.innerHTML = svg;
        setError(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Diagram render failed");
    }
  }, [code, uniqueId]);

  useEffect(() => {
    render();
  }, [render]);

  if (error) {
    return (
      <div className="my-2 rounded-lg border border-zinc-800 bg-zinc-950 overflow-hidden">
        <div className="border-b border-zinc-800 px-3 py-1 text-[10px] font-mono text-zinc-500 uppercase">
          mermaid
        </div>
        <pre className="overflow-x-auto p-3">
          <code className="text-xs font-mono text-zinc-300 leading-relaxed">{code}</code>
        </pre>
      </div>
    );
  }

  return (
    <div className="my-2 rounded-lg border border-zinc-800 bg-zinc-950/80 overflow-x-auto p-4">
      <div ref={containerRef} className="flex justify-center [&>svg]:max-w-full" />
    </div>
  );
}

const defaultComponents: Components = {
  h1: ({ children }) => (
    <h1 className="mt-4 mb-2 text-base font-bold text-zinc-100">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="mt-4 mb-2 text-sm font-bold text-zinc-100">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="mt-3 mb-1.5 text-sm font-semibold text-zinc-200">{children}</h3>
  ),
  h4: ({ children }) => (
    <h4 className="mt-2 mb-1 text-xs font-semibold text-zinc-300">{children}</h4>
  ),
  p: ({ children }) => (
    <p className="mb-2 text-sm leading-relaxed text-zinc-300">{children}</p>
  ),
  ul: ({ children }) => (
    <ul className="mb-2 ml-4 list-disc space-y-0.5 text-sm text-zinc-300">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-2 ml-4 list-decimal space-y-0.5 text-sm text-zinc-300">{children}</ol>
  ),
  li: ({ children }) => (
    <li className="leading-relaxed">{children}</li>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold text-zinc-100">{children}</strong>
  ),
  em: ({ children }) => (
    <em className="italic text-zinc-400">{children}</em>
  ),
  code: ({ className, children, ...props }) => {
    const isBlock = className?.includes("language-");
    if (isBlock) {
      const lang = className?.replace("language-", "") || "";
      if (lang === "mermaid") {
        const text = String(children).replace(/\n$/, "");
        return <MermaidDiagram code={text} />;
      }
      return (
        <div className="my-2 rounded-lg border border-zinc-800 bg-zinc-950 overflow-hidden">
          {lang && (
            <div className="border-b border-zinc-800 px-3 py-1 text-[10px] font-mono text-zinc-500 uppercase">
              {lang}
            </div>
          )}
          <pre className="overflow-x-auto p-3">
            <code className="text-xs font-mono text-zinc-300 leading-relaxed" {...props}>
              {children}
            </code>
          </pre>
        </div>
      );
    }
    return (
      <code className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs font-mono text-zinc-200" {...props}>
        {children}
      </code>
    );
  },
  pre: ({ children }) => <>{children}</>,
  blockquote: ({ children }) => (
    <blockquote className="my-2 border-l-2 border-zinc-600 pl-3 text-sm italic text-zinc-400">
      {children}
    </blockquote>
  ),
  table: ({ children }) => (
    <div className="my-2 overflow-x-auto rounded-lg border border-zinc-800">
      <table className="w-full text-xs">{children}</table>
    </div>
  ),
  thead: ({ children }) => (
    <thead className="border-b border-zinc-700 bg-zinc-900">{children}</thead>
  ),
  th: ({ children }) => (
    <th className="px-3 py-1.5 text-left font-semibold text-zinc-300">{children}</th>
  ),
  td: ({ children }) => (
    <td className="border-t border-zinc-800/50 px-3 py-1.5 text-zinc-400">{children}</td>
  ),
  hr: () => <hr className="my-3 border-zinc-800" />,
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-zinc-300 underline decoration-zinc-500/40 hover:decoration-zinc-300 transition-colors"
    >
      {children}
    </a>
  ),
};

const terminalComponents: Components = {
  h1: ({ children }) => (
    <h1 className="mt-3 mb-1.5 text-xs font-bold text-emerald-300">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="mt-3 mb-1.5 text-xs font-bold text-emerald-300">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="mt-2 mb-1 text-xs font-semibold text-emerald-400">{children}</h3>
  ),
  h4: ({ children }) => (
    <h4 className="mt-1.5 mb-0.5 text-[11px] font-semibold text-emerald-400">{children}</h4>
  ),
  p: ({ children }) => (
    <p className="mb-1.5 text-xs leading-relaxed text-emerald-400/90">{children}</p>
  ),
  ul: ({ children }) => (
    <ul className="mb-1.5 ml-3 list-disc space-y-0.5 text-xs text-emerald-400/90">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-1.5 ml-3 list-decimal space-y-0.5 text-xs text-emerald-400/90">{children}</ol>
  ),
  li: ({ children }) => (
    <li className="leading-relaxed">{children}</li>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold text-emerald-300">{children}</strong>
  ),
  em: ({ children }) => (
    <em className="italic text-emerald-500/80">{children}</em>
  ),
  code: ({ className, children, ...props }) => {
    const isBlock = className?.includes("language-");
    if (isBlock) {
      const lang = className?.replace("language-", "") || "";
      if (lang === "mermaid") {
        const text = String(children).replace(/\n$/, "");
        return <MermaidDiagram code={text} />;
      }
      return (
        <div className="my-1.5 rounded border border-emerald-900/40 bg-black/40 overflow-hidden">
          {lang && (
            <div className="border-b border-emerald-900/30 px-2.5 py-0.5 text-[9px] font-mono text-emerald-600 uppercase">
              {lang}
            </div>
          )}
          <pre className="overflow-x-auto p-2.5">
            <code className="text-[11px] font-mono text-emerald-300/80 leading-relaxed" {...props}>
              {children}
            </code>
          </pre>
        </div>
      );
    }
    return (
      <code className="rounded bg-emerald-950/40 px-1 py-0.5 text-[11px] font-mono text-emerald-300" {...props}>
        {children}
      </code>
    );
  },
  pre: ({ children }) => <>{children}</>,
  blockquote: ({ children }) => (
    <blockquote className="my-1.5 border-l-2 border-emerald-800/50 pl-2.5 text-xs italic text-emerald-500/70">
      {children}
    </blockquote>
  ),
  table: ({ children }) => (
    <div className="my-1.5 overflow-x-auto rounded border border-emerald-900/40">
      <table className="w-full text-[11px]">{children}</table>
    </div>
  ),
  thead: ({ children }) => (
    <thead className="border-b border-emerald-900/40 bg-emerald-950/20">{children}</thead>
  ),
  th: ({ children }) => (
    <th className="px-2.5 py-1 text-left font-semibold text-emerald-300">{children}</th>
  ),
  td: ({ children }) => (
    <td className="border-t border-emerald-900/30 px-2.5 py-1 text-emerald-400/80">{children}</td>
  ),
  hr: () => <hr className="my-2 border-emerald-900/40" />,
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-emerald-300 underline decoration-emerald-700/50 hover:decoration-emerald-400 transition-colors"
    >
      {children}
    </a>
  ),
};

const MERMAID_START =
  /^(graph\s+(TD|TB|BT|LR|RL)|flowchart\s+(TD|TB|BT|LR|RL)|sequenceDiagram|classDiagram|stateDiagram|erDiagram|gantt|pie|gitgraph)\s*$/;

const MERMAID_LINE =
  /^\s*([\w[\]()"|{}]+\s*(-->|---|-\.->|==>|-.->|--\s|~~~|-->|<-->)\s*[\w[\]()"|{}]+|subgraph\s|end\s*$|%%|style\s|class\s|linkStyle\s|\w+\s*-->|participant\s|\w+\s*->>|Note\s|loop\s|alt\s|else\s|opt\s)/;

export function wrapRawMermaid(text: string): string {
  const lines = text.split("\n");
  const result: string[] = [];
  let i = 0;
  let insideFence = false;

  while (i < lines.length) {
    const trimmed = lines[i].trim();

    if (trimmed.startsWith("```")) {
      if (insideFence) {
        insideFence = false;
        result.push(lines[i]);
        i++;
        continue;
      }
      if (trimmed.startsWith("```mermaid")) {
        insideFence = true;
        result.push(lines[i]);
        i++;
        continue;
      }
      insideFence = true;
      result.push(lines[i]);
      i++;
      continue;
    }

    if (insideFence) {
      result.push(lines[i]);
      i++;
      continue;
    }

    if (/^MERMAID\s*$/i.test(trimmed)) {
      i++;
      continue;
    }

    if (MERMAID_START.test(trimmed)) {
      const block: string[] = [lines[i]];
      let j = i + 1;
      while (j < lines.length) {
        const lt = lines[j].trim();
        if (lt.startsWith("```")) break;
        if (lt === "" && j + 1 < lines.length && !MERMAID_LINE.test(lines[j + 1].trim())) break;
        if (lt === "" || MERMAID_LINE.test(lt) || /^\s/.test(lines[j])) {
          block.push(lines[j]);
          j++;
        } else {
          break;
        }
      }
      if (block.length > 1) {
        result.push("```mermaid");
        result.push(...block);
        result.push("```");
        i = j;
        continue;
      }
    }
    result.push(lines[i]);
    i++;
  }
  return result.join("\n");
}

export function Markdown({ content, terminal }: { content: string; terminal?: boolean }) {
  const processed = useMemo(() => wrapRawMermaid(content), [content]);
  return (
    <div className={terminal ? "markdown-body font-mono" : "markdown-body"}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={terminal ? terminalComponents : defaultComponents}
      >
        {processed}
      </ReactMarkdown>
    </div>
  );
}
