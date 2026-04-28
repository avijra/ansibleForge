import { User } from "lucide-react";
import type { AgentEvent } from "@/api/types";

export function UserMessageEvent({ event }: { event: AgentEvent }) {
  const content = (event.data.content as string) || "";

  if (!content) return null;

  return (
    <div className="animate-slide-in flex justify-end">
      <div className="max-w-[85%] rounded-xl rounded-br-sm border border-zinc-700/60 bg-zinc-800 px-4 py-3">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1 text-sm leading-relaxed text-zinc-100 whitespace-pre-wrap">
            {content}
          </div>
          <div className="mt-0.5 shrink-0 rounded-lg bg-zinc-700/50 p-1.5">
            <User className="h-3.5 w-3.5 text-zinc-400" />
          </div>
        </div>
      </div>
    </div>
  );
}
