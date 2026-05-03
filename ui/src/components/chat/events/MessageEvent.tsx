import type { AgentEvent } from "@/api/types";
import { Markdown } from "@/components/chat/Markdown";

export function MessageEvent({ event }: { event: AgentEvent }) {
  const content = (event.data.content as string) || "";
  const usage = event.data.usage as Record<string, number> | undefined;
  const isStreaming = event.data._streaming === true;

  if (!content && !isStreaming) return null;

  return (
    <div className="animate-slide-in rounded-lg border border-emerald-900/50 bg-black/60 px-3 py-2.5 font-mono">
      <div className="flex items-center gap-1.5 mb-1.5 text-[10px] text-emerald-600">
        <span className="text-emerald-500">$</span>
        <span>tuyere</span>
        {isStreaming && <span className="animate-pulse">...</span>}
      </div>
      <Markdown content={content} terminal />
      {isStreaming && (
        <span className="inline-block w-1.5 h-3.5 ml-0.5 bg-emerald-500 animate-pulse rounded-sm align-text-bottom" />
      )}
      {!isStreaming && usage && usage.total_tokens > 0 && (
        <div className="mt-2 flex items-center gap-2.5 text-[9px] font-mono text-emerald-800">
          <span>{usage.total_tokens?.toLocaleString()} tok</span>
          <span className="text-emerald-900">|</span>
          <span>{usage.prompt_tokens?.toLocaleString()} in</span>
          <span className="text-emerald-900">|</span>
          <span>{usage.completion_tokens?.toLocaleString()} out</span>
        </div>
      )}
    </div>
  );
}
