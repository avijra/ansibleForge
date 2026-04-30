import { useCallback, useLayoutEffect, useRef } from "react";
import type { AgentEvent } from "@/api/types";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { ThinkingEvent } from "./events/ThinkingEvent";
import { ToolCallEvent } from "./events/ToolCallEvent";
import { ToolResultEvent } from "./events/ToolResultEvent";
import { DiffReview } from "@/components/review/DiffReview";
import { MessageEvent } from "./events/MessageEvent";
import { ErrorEvent } from "./events/ErrorEvent";
import { UserMessageEvent } from "./events/UserMessageEvent";
import { SecretRequestEvent } from "./events/SecretRequestEvent";
import { EmptyState } from "./EmptyState";

const SCROLL_THRESHOLD = 150;

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
  const containerRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const isAutoScrolling = useRef(false);

  const handleScroll = useCallback(() => {
    if (isAutoScrolling.current) return;
    const el = containerRef.current;
    if (!el) return;
    stickToBottom.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < SCROLL_THRESHOLD;
  }, []);

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el || !stickToBottom.current) return;
    isAutoScrolling.current = true;
    el.scrollTop = el.scrollHeight;
    requestAnimationFrame(() => {
      isAutoScrolling.current = false;
    });
  }, [events, isStreaming]);

  if (events.length === 0 && !isStreaming) {
    return <EmptyState onAction={onQuickAction || (() => {})} />;
  }

  return (
    <div ref={containerRef} onScroll={handleScroll} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
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
              <DiffReview
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
          case "progress": {
            const elapsed = event.data.elapsed_seconds as number;
            const tool = event.data.tool as string;
            const msg = event.data.message as string;
            const mins = Math.floor(elapsed / 60);
            const secs = elapsed % 60;
            const timeStr = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
            return (
              <div
                key={event.id}
                className="flex items-center gap-2.5 py-1.5 text-xs text-zinc-500 animate-pulse"
              >
                <svg className="h-3 w-3 animate-spin text-zinc-500" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" />
                  <path className="opacity-60" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                <span className="text-zinc-500">{msg}</span>
                <span className="ml-auto font-mono text-[10px] text-zinc-600">{tool} · {timeStr}</span>
              </div>
            );
          }
          case "approval_granted":
            return (
              <div
                key={event.id}
                className="animate-slide-in rounded-lg bg-emerald-950/15 border border-emerald-800/30 shadow-[0_0_12px_-4px_rgba(16,185,129,0.10)] px-4 py-2.5 text-xs text-zinc-400 font-medium"
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
      {isStreaming && (() => {
        const lastProgress = [...events].reverse().find((e) => e.event === "progress");
        const msg = lastProgress
          ? (lastProgress.data.message as string)
          : "Hold on. I'm thinking. Don't rush me.";
        return (
          <div className="flex items-center gap-2.5 py-3 text-xs text-zinc-500">
            <LoadingSpinner />
            <span className="animate-pulse">{msg}</span>
          </div>
        );
      })()}
    </div>
  );
}
