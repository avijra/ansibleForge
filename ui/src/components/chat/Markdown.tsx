import { useEffect, useId, useMemo, useRef, useState } from "react";
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

const svgCache = new Map<string, string>();

// LLMs frequently emit "smart" Unicode punctuation (curly quotes, en/em dashes,
// ellipses, non-breaking spaces) inside diagram labels, which the Mermaid parser
// rejects. Normalize to ASCII equivalents so diagrams render instead of erroring.
function sanitizeMermaid(code: string): string {
  return code
    .replace(/[\u201C\u201D\u201E\u201F\u00AB\u00BB]/g, '"')
    .replace(/[\u2018\u2019\u201A\u201B]/g, "'")
    .replace(/[\u2013\u2014\u2015]/g, "-")
    .replace(/\u2026/g, "...")
    .replace(/\u00A0/g, " ");
}

type QueueEntry = { code: string; id: string; resolve: (svg: string) => void; reject: (err: Error) => void };
const renderQueue: QueueEntry[] = [];
let rendering = false;

async function drainQueue() {
  if (rendering) return;
  rendering = true;
  while (renderQueue.length > 0) {
    const entry = renderQueue.shift()!;
    const cached = svgCache.get(entry.code);
    if (cached) {
      entry.resolve(cached);
      continue;
    }
    try {
      const { svg } = await mermaid.render(entry.id, sanitizeMermaid(entry.code));
      svgCache.set(entry.code, svg);
      entry.resolve(svg);
    } catch (err) {
      entry.reject(err instanceof Error ? err : new Error("Diagram render failed"));
    }
    await new Promise((r) => setTimeout(r, 0));
  }
  rendering = false;
}

function enqueueRender(code: string, id: string): Promise<string> {
  const cached = svgCache.get(code);
  if (cached) return Promise.resolve(cached);
  return new Promise((resolve, reject) => {
    renderQueue.push({ code, id, resolve, reject });
    drainQueue();
  });
}

function MermaidDiagram({ code }: { code: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"loading" | "done" | "error">(
    svgCache.has(code) ? "done" : "loading"
  );
  const [error, setError] = useState<string | null>(null);
  const uniqueId = useId().replace(/:/g, "_");
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const dragRef = useRef<{ startX: number; startY: number; panX: number; panY: number } | null>(null);

  useEffect(() => {
    let cancelled = false;
    const cached = svgCache.get(code);
    if (cached && containerRef.current) {
      containerRef.current.innerHTML = cached;
      setState("done");
      return;
    }
    setState("loading");
    enqueueRender(code, `mermaid_${uniqueId}`).then(
      (svg) => {
        if (cancelled || !containerRef.current) return;
        containerRef.current.innerHTML = svg;
        setState("done");
        setError(null);
      },
      (err) => {
        if (cancelled) return;
        setState("error");
        setError(err instanceof Error ? err.message : "Diagram render failed");
      }
    );
    return () => { cancelled = true; };
  }, [code, uniqueId]);

  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      setZoom((z) => Math.min(5, Math.max(0.2, z - e.deltaY * 0.002)));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    dragRef.current = { startX: e.clientX, startY: e.clientY, panX: pan.x, panY: pan.y };
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragRef.current) return;
    setPan({
      x: dragRef.current.panX + (e.clientX - dragRef.current.startX),
      y: dragRef.current.panY + (e.clientY - dragRef.current.startY),
    });
  };
  const onPointerUp = () => { dragRef.current = null; };

  const resetView = () => { setZoom(1); setPan({ x: 0, y: 0 }); };
  const isTransformed = zoom !== 1 || pan.x !== 0 || pan.y !== 0;

  if (state === "error") {
    return (
      <div className="my-2 rounded-lg border border-zinc-800 bg-zinc-950 overflow-hidden">
        <div className="border-b border-zinc-800 px-3 py-1 text-[10px] font-mono text-zinc-500 uppercase">
          mermaid
        </div>
        <pre className="overflow-x-auto p-3">
          <code className="text-xs font-mono text-zinc-300 leading-relaxed">{code}</code>
        </pre>
        {error && <div className="px-3 pb-2 text-[10px] text-red-400">{error}</div>}
      </div>
    );
  }

  return (
    <div className="group/diagram my-2 rounded-lg border border-zinc-800 bg-zinc-950/80 overflow-hidden relative">
      <div
        className="absolute top-2 right-2 z-10 flex items-center gap-0.5 rounded-md border border-zinc-700/60 bg-zinc-900/90 p-0.5 opacity-0 transition-opacity group-hover/diagram:opacity-100"
      >
        <button
          onClick={() => setZoom((z) => Math.min(5, z + 0.25))}
          className="flex h-6 w-6 items-center justify-center rounded text-zinc-400 hover:bg-zinc-700/60 hover:text-zinc-200 transition-colors"
          title="Zoom in"
        >
          <svg viewBox="0 0 16 16" fill="currentColor" className="h-3 w-3"><path d="M8 4a.5.5 0 01.5.5v3h3a.5.5 0 010 1h-3v3a.5.5 0 01-1 0v-3h-3a.5.5 0 010-1h3v-3A.5.5 0 018 4z"/></svg>
        </button>
        <span className="min-w-[32px] text-center text-[9px] tabular-nums text-zinc-500 select-none">
          {Math.round(zoom * 100)}%
        </span>
        <button
          onClick={() => setZoom((z) => Math.max(0.2, z - 0.25))}
          className="flex h-6 w-6 items-center justify-center rounded text-zinc-400 hover:bg-zinc-700/60 hover:text-zinc-200 transition-colors"
          title="Zoom out"
        >
          <svg viewBox="0 0 16 16" fill="currentColor" className="h-3 w-3"><path d="M4 8a.5.5 0 01.5-.5h7a.5.5 0 010 1h-7A.5.5 0 014 8z"/></svg>
        </button>
        {isTransformed && (
          <button
            onClick={resetView}
            className="flex h-6 w-6 items-center justify-center rounded text-zinc-400 hover:bg-zinc-700/60 hover:text-zinc-200 transition-colors"
            title="Reset view"
          >
            <svg viewBox="0 0 16 16" fill="currentColor" className="h-3 w-3"><path d="M1 8a7 7 0 1113.06-3.5h-2.12A5 5 0 008 3a5 5 0 100 10 5 5 0 003.54-1.46l1.41 1.41A7 7 0 011 8z"/><path d="M14 1v4h-4l1.5-1.5L14 1z"/></svg>
          </button>
        )}
      </div>
      <div
        ref={viewportRef}
        className="overflow-hidden p-4"
        style={{ cursor: dragRef.current ? "grabbing" : "grab" }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        {state === "loading" && (
          <div className="flex items-center justify-center gap-2 py-3 text-[11px] text-zinc-500">
            <svg className="h-3.5 w-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Rendering diagram…
          </div>
        )}
        <div
          ref={containerRef}
          className="flex justify-center [&>svg]:max-w-none transition-transform duration-75"
          style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`, transformOrigin: "center center" }}
        />
      </div>
      {isTransformed && (
        <div className="absolute bottom-1.5 left-1/2 -translate-x-1/2 text-[9px] text-zinc-600 select-none pointer-events-none">
          Ctrl+scroll to zoom · drag to pan
        </div>
      )}
    </div>
  );
}

const MERMAID_KEYWORD_RE =
  /^\s*(graph\s+(TD|TB|BT|LR|RL)|flowchart\s+(TD|TB|BT|LR|RL)|sequenceDiagram|classDiagram|stateDiagram(-v2)?|erDiagram|gantt|pie\b|gitgraph|journey|mindmap|timeline|C4Context|C4Container|C4Component|C4Dynamic|C4Deployment|quadrantChart|requirementDiagram|block-beta|sankey-beta|xychart-beta|packet-beta|kanban|architecture-beta)/;

const DIAGRAM_SYNTAX_RE =
  /(-->|==>|->>|---|~~~|<-->|->|--x|--o|\.\->|subgraph |end$|participant |Note |style |class |linkStyle |rect |loop |alt |else |opt |par |critical |break |activate |deactivate |%%|\|.*\||:::|click )/;

type ContentSegment = { type: "text" | "mermaid"; content: string };

function extractSegments(text: string): ContentSegment[] {
  const segments: ContentSegment[] = [];
  const lines = text.split("\n");
  let textBuf: string[] = [];
  let i = 0;

  function flush() {
    if (textBuf.length > 0) {
      segments.push({ type: "text", content: textBuf.join("\n") });
      textBuf = [];
    }
  }

  while (i < lines.length) {
    const trimmed = lines[i].trim();

    if (/^```mermaid/i.test(trimmed)) {
      flush();
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        buf.push(lines[i]);
        i++;
      }
      if (i < lines.length) i++;
      if (buf.length) segments.push({ type: "mermaid", content: buf.join("\n") });
      continue;
    }

    if (trimmed.startsWith("```")) {
      const fenceLang = trimmed.slice(3).trim().toLowerCase();
      const peek = i + 1 < lines.length ? lines[i + 1].trim() : "";
      const isMermaidInside = !fenceLang && MERMAID_KEYWORD_RE.test(peek);

      if (isMermaidInside) {
        flush();
        const buf: string[] = [];
        i++;
        while (i < lines.length && !lines[i].trim().startsWith("```")) {
          buf.push(lines[i]);
          i++;
        }
        if (i < lines.length) i++;
        if (buf.length) segments.push({ type: "mermaid", content: buf.join("\n") });
      } else {
        textBuf.push(lines[i]);
        i++;
        while (i < lines.length && !lines[i].trim().startsWith("```")) {
          textBuf.push(lines[i]);
          i++;
        }
        if (i < lines.length) {
          textBuf.push(lines[i]);
          i++;
        }
      }
      continue;
    }

    if (/^MERMAID\s*$/i.test(trimmed)) {
      i++;
      continue;
    }

    if (MERMAID_KEYWORD_RE.test(trimmed)) {
      flush();
      const buf: string[] = [lines[i]];
      i++;
      let emptyRun = 0;
      while (i < lines.length) {
        const lt = lines[i].trim();
        if (lt.startsWith("```")) break;
        if (/^#{1,6}\s/.test(lt)) break;
        if (lt === "") {
          emptyRun++;
          if (emptyRun >= 2) break;
          buf.push(lines[i]);
          i++;
          continue;
        }
        emptyRun = 0;
        const atCol0 = !/^\s/.test(lines[i]);
        const hasSyntax = DIAGRAM_SYNTAX_RE.test(lt);
        if (atCol0 && lt.length > 40 && !hasSyntax) break;
        buf.push(lines[i]);
        i++;
      }
      while (buf.length > 1 && buf[buf.length - 1].trim() === "") buf.pop();
      if (buf.length > 1) {
        segments.push({ type: "mermaid", content: buf.join("\n") });
      } else {
        textBuf.push(...buf);
      }
      continue;
    }

    textBuf.push(lines[i]);
    i++;
  }

  flush();
  return segments;
}

function makeMermaidAwareCode(styles: {
  blockWrap: string;
  langLabel: string;
  pre: string;
  codeBlock: string;
  codeInline: string;
}): Components["code"] {
  return ({ className, children, ...props }) => {
    const lang = className?.replace("language-", "") || "";
    const text = String(children).replace(/\n$/, "");
    const isBlock = !!lang || text.includes("\n");

    if (isBlock) {
      if (lang === "mermaid" || (!lang && MERMAID_KEYWORD_RE.test(text.trim()))) {
        return <MermaidDiagram code={text} />;
      }
      return (
        <div className={styles.blockWrap}>
          {lang && <div className={styles.langLabel}>{lang}</div>}
          <pre className={styles.pre}>
            <code className={styles.codeBlock} {...props}>
              {children}
            </code>
          </pre>
        </div>
      );
    }
    return (
      <code className={styles.codeInline} {...props}>
        {children}
      </code>
    );
  };
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
  code: makeMermaidAwareCode({
    blockWrap: "my-2 rounded-lg border border-zinc-800 bg-zinc-950 overflow-hidden",
    langLabel:
      "border-b border-zinc-800 px-3 py-1 text-[10px] font-mono text-zinc-500 uppercase",
    pre: "overflow-x-auto p-3",
    codeBlock: "text-xs font-mono text-zinc-300 leading-relaxed",
    codeInline:
      "rounded bg-zinc-800 px-1.5 py-0.5 text-xs font-mono text-zinc-200",
  }),
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
  code: makeMermaidAwareCode({
    blockWrap:
      "my-1.5 rounded border border-emerald-900/40 bg-black/40 overflow-hidden",
    langLabel:
      "border-b border-emerald-900/30 px-2.5 py-0.5 text-[9px] font-mono text-emerald-600 uppercase",
    pre: "overflow-x-auto p-2.5",
    codeBlock: "text-[11px] font-mono text-emerald-300/80 leading-relaxed",
    codeInline:
      "rounded bg-emerald-950/40 px-1 py-0.5 text-[11px] font-mono text-emerald-300",
  }),
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

function MermaidPreview({ code }: { code: string }) {
  return (
    <div className="my-2 rounded-lg border border-zinc-800 bg-zinc-950 overflow-hidden">
      <div className="border-b border-zinc-800 px-3 py-1 flex items-center gap-2">
        <span className="text-[10px] font-mono text-zinc-500 uppercase">mermaid</span>
        <span className="text-[9px] text-zinc-600 animate-pulse">rendering when complete…</span>
      </div>
      <pre className="overflow-x-auto p-3">
        <code className="text-xs font-mono text-zinc-400 leading-relaxed">{code}</code>
      </pre>
    </div>
  );
}

function stableKey(content: string): string {
  let h = 0;
  for (let i = 0; i < content.length; i++) {
    h = ((h << 5) - h + content.charCodeAt(i)) | 0;
  }
  return (h >>> 0).toString(36);
}

export function Markdown({
  content,
  terminal,
  streaming,
}: {
  content: string;
  terminal?: boolean;
  streaming?: boolean;
}) {
  const segments = useMemo(() => extractSegments(content), [content]);
  const components = terminal ? terminalComponents : defaultComponents;

  return (
    <div className={terminal ? "markdown-body font-mono" : "markdown-body"}>
      {segments.map((seg, idx) =>
        seg.type === "mermaid" ? (
          streaming ? (
            <MermaidPreview key={`m-${stableKey(seg.content)}`} code={seg.content} />
          ) : (
            <MermaidDiagram key={`m-${stableKey(seg.content)}`} code={seg.content} />
          )
        ) : (
          <ReactMarkdown
            key={idx}
            remarkPlugins={[remarkGfm]}
            components={components}
          >
            {seg.content}
          </ReactMarkdown>
        ),
      )}
    </div>
  );
}
