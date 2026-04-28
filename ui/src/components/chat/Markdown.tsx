import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

const components: Components = {
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
      <code className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs font-mono text-teal-300" {...props}>
        {children}
      </code>
    );
  },
  pre: ({ children }) => <>{children}</>,
  blockquote: ({ children }) => (
    <blockquote className="my-2 border-l-2 border-teal-500/40 pl-3 text-sm italic text-zinc-400">
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
      className="text-teal-400 underline decoration-teal-400/30 hover:decoration-teal-400 transition-colors"
    >
      {children}
    </a>
  ),
};

export function Markdown({ content }: { content: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
