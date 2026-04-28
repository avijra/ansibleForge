import { Brain, ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import type { AgentEvent } from "@/api/types";
import { cn } from "@/lib/utils";
import { Markdown } from "@/components/chat/Markdown";

export function ThinkingEvent({ event }: { event: AgentEvent }) {
  const [expanded, setExpanded] = useState(true);
  const content = (event.data.content as string) || "";

  if (!content) return null;

  return (
    <div className="animate-slide-in rounded-lg border border-violet-800/20 bg-violet-950/10 px-3 py-2.5">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 text-xs text-violet-300/70 hover:text-violet-200 transition-colors"
      >
        <Brain className="h-3.5 w-3.5 text-violet-400/70" />
        <span className="font-medium">Thinking</span>
        {expanded ? (
          <ChevronDown className="ml-auto h-3.5 w-3.5" />
        ) : (
          <>
            <span className="ml-2 flex-1 truncate text-left text-zinc-500 font-normal">
              {content.slice(0, 100)}...
            </span>
            <ChevronRight className="ml-auto h-3.5 w-3.5" />
          </>
        )}
      </button>
      <div
        className={cn(
          "overflow-hidden transition-all duration-200",
          expanded ? "mt-2 max-h-[32rem]" : "max-h-0"
        )}
      >
        <div className="text-xs leading-relaxed text-zinc-400">
          <Markdown content={content} />
        </div>
      </div>
    </div>
  );
}
