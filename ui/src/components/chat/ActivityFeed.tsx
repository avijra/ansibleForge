import { useEffect, useRef } from "react";
import type { AgentEvent } from "@/api/types";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { ThinkingEvent } from "./events/ThinkingEvent";
import { ToolCallEvent } from "./events/ToolCallEvent";
import { ToolResultEvent } from "./events/ToolResultEvent";
import { ApprovalEvent } from "./events/ApprovalEvent";
import { MessageEvent } from "./events/MessageEvent";
import { ErrorEvent } from "./events/ErrorEvent";
import { UserMessageEvent } from "./events/UserMessageEvent";
import { SecretRequestEvent } from "./events/SecretRequestEvent";
import { EmptyState } from "./EmptyState";

interface ActivityFeedProps {
  events: AgentEvent[];
  isStreaming: boolean;
  isPendingApproval: boolean;
  onApprove: () => void;
  onReject: () => void;
  onQuickAction?: (prompt: string) => void;
}

export function ActivityFeed({
  events,
  isStreaming,
  isPendingApproval,
  onApprove,
  onReject,
  onQuickAction,
}: ActivityFeedProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  const lastEvent = events[events.length - 1];
  const scrollKey = lastEvent
    ? `${events.length}-${String(lastEvent.data?.content ?? "").length}`
    : "0";

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [scrollKey]);

  if (events.length === 0 && !isStreaming) {
    return <EmptyState onAction={onQuickAction || (() => {})} />;
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
      {events.map((event) => {
        switch (event.event) {
          case "user_message":
            return <UserMessageEvent key={event.id} event={event} />;
          case "thinking":
            return <ThinkingEvent key={event.id} event={event} />;
          case "tool_call":
            return <ToolCallEvent key={event.id} event={event} />;
          case "tool_result":
            return <ToolResultEvent key={event.id} event={event} />;
          case "secret_request":
            return <SecretRequestEvent key={event.id} event={event} />;
          case "approval_required":
            return (
              <ApprovalEvent
                key={event.id}
                event={event}
                isPending={isPendingApproval}
                onApprove={onApprove}
                onReject={onReject}
              />
            );
          case "message":
            return <MessageEvent key={event.id} event={event} />;
          case "error_recovery":
          case "max_steps":
            return <ErrorEvent key={event.id} event={event} />;
          case "step_start": {
            const step = event.data.step as number;
            if (step === 1) return null;
            return (
              <div
                key={event.id}
                className="flex items-center gap-2 py-0.5 text-[10px] font-mono text-zinc-700"
              >
                <span className="h-px flex-1 bg-zinc-800/60" />
                step {step}
                <span className="h-px flex-1 bg-zinc-800/60" />
              </div>
            );
          }
          case "approval_granted":
            return (
              <div
                key={event.id}
                className="animate-slide-in rounded-lg bg-emerald-950/30 border border-emerald-800/40 px-4 py-2.5 text-xs text-emerald-400 font-medium"
              >
                Approved — executing...
              </div>
            );
          case "approval_rejected":
            return (
              <div
                key={event.id}
                className="animate-slide-in rounded-lg bg-zinc-900 border border-zinc-800 px-4 py-2.5 text-xs text-zinc-400"
              >
                Rejected. {event.data.feedback as string}
              </div>
            );
          default:
            return null;
        }
      })}
      {isStreaming && (
        <div className="flex items-center gap-2.5 py-3 text-xs text-zinc-500">
          <LoadingSpinner />
          <span className="animate-pulse">AnsibleForge is working...</span>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  );
}
