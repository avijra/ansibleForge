import { Terminal } from "lucide-react";
import type { AgentEvent } from "@/api/types";
import { Markdown } from "@/components/chat/Markdown";

export function MessageEvent({ event }: { event: AgentEvent }) {
  const content = (event.data.content as string) || "";
  const usage = event.data.usage as Record<string, number> | undefined;

  if (!content) return null;

  return (
    <div className="animate-slide-in rounded-xl border border-zinc-800 bg-gradient-to-b from-zinc-900/80 to-zinc-900/40 p-4">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 shrink-0 rounded-lg bg-teal-500/10 p-2 ring-1 ring-teal-500/20">
          <Terminal className="h-4 w-4 text-teal-400" />
        </div>
        <div className="min-w-0 flex-1">
          <Markdown content={content} />
          {usage && usage.total_tokens > 0 && (
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
