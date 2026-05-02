import type { AgentEvent } from "@/api/types";
import { Markdown } from "@/components/chat/Markdown";
import { TuyereLogo } from "@/components/common/TuyereLogo";

export function MessageEvent({ event }: { event: AgentEvent }) {
  const content = (event.data.content as string) || "";
  const usage = event.data.usage as Record<string, number> | undefined;
  const isStreaming = event.data._streaming === true;

  if (!content && !isStreaming) return null;

  return (
    <div
      className="animate-slide-in rounded-xl border border-emerald-700/40 bg-gradient-to-b from-zinc-900/90 to-zinc-950/60 p-4"
      style={{
        boxShadow:
          "0 0 10px -2px rgba(16, 185, 129, 0.18), 0 0 24px -4px rgba(16, 185, 129, 0.10), 0 1px 3px rgba(0,0,0,0.3)",
      }}
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 shrink-0 rounded-md bg-emerald-950/40 p-1.5">
          <TuyereLogo
            size={16}
            animate={isStreaming}
            className="text-emerald-500"
          />
        </div>
        <div className="min-w-0 flex-1">
          <Markdown content={content} />
          {isStreaming && (
            <span className="inline-block w-2 h-4 ml-0.5 bg-emerald-400 animate-pulse rounded-sm align-text-bottom" />
          )}
          {!isStreaming && usage && usage.total_tokens > 0 && (
            <div className="mt-3 flex items-center gap-3 text-[10px] font-mono text-zinc-600">
              <span>{usage.total_tokens?.toLocaleString()} tokens</span>
              <span className="h-1 w-1 rounded-full bg-zinc-700" />
              <span>{usage.prompt_tokens?.toLocaleString()} in</span>
              <span className="h-1 w-1 rounded-full bg-zinc-700" />
              <span>{usage.completion_tokens?.toLocaleString()} out</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
