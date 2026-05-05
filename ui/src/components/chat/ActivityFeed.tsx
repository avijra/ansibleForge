import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, Loader2, MessageSquare, WifiOff, Circle, XCircle as XC, MinusCircle } from "lucide-react";
import type { AgentEvent, Session } from "@/api/types";
import { friendlyToolName } from "@/lib/tool-labels";
import { DiffReview } from "@/components/review/DiffReview";
import { MessageEvent } from "./events/MessageEvent";
import { ErrorEvent } from "./events/ErrorEvent";
import { PlanEvent } from "./events/PlanEvent";
import { UserMessageEvent } from "./events/UserMessageEvent";
import { SecretRequestEvent } from "./events/SecretRequestEvent";
import { EmptyState } from "./EmptyState";

const SCROLL_THRESHOLD = 150;

interface StepGroup {
  stepNum: number;
  events: AgentEvent[];
  isComplete: boolean;
  toolSummary: string;
  status: "success" | "error" | "running";
}

function groupEventsIntoSteps(events: AgentEvent[]): (AgentEvent | StepGroup)[] {
  const result: (AgentEvent | StepGroup)[] = [];
  let currentStep: StepGroup | null = null;

  const TOP_LEVEL = new Set([
    "user_message", "message", "plan", "max_steps",
    "secret_request", "approval_required", "error_recovery",
  ]);

  const STEP_EVENTS = new Set([
    "step_start", "thinking", "tool_call", "tool_result",
    "progress", "live_log", "checkpoint", "error_recovery",
    "approval_granted", "approval_rejected",
  ]);

  for (const event of events) {
    if (event.event === "step_start") {
      if (currentStep) {
        currentStep.isComplete = true;
        result.push(currentStep);
      }
      currentStep = {
        stepNum: (event.data.step as number) || 1,
        events: [event],
        isComplete: false,
        toolSummary: "",
        status: "running",
      };
      continue;
    }

    if (currentStep && STEP_EVENTS.has(event.event)) {
      currentStep.events.push(event);

      if (event.event === "tool_call") {
        const tool = (event.data.tool as string) || "";
        const existing = currentStep.toolSummary;
        currentStep.toolSummary = existing
          ? `${existing}, ${friendlyToolName(tool)}`
          : friendlyToolName(tool);
      }

      if (event.event === "tool_result") {
        const status = (event.data.status as string) || "success";
        if (status === "error" || status === "failed") {
          currentStep.status = "error";
        } else if (currentStep.status !== "error") {
          currentStep.status = "success";
        }
      }
      continue;
    }

    if (TOP_LEVEL.has(event.event)) {
      if (currentStep) {
        currentStep.isComplete = true;
        result.push(currentStep);
        currentStep = null;
      }
      result.push(event);
      continue;
    }

    if (currentStep) {
      currentStep.events.push(event);
    } else {
      result.push(event);
    }
  }

  if (currentStep) result.push(currentStep);
  return result;
}

function isStepGroup(item: AgentEvent | StepGroup): item is StepGroup {
  return "stepNum" in item && "events" in item;
}

function LiveTaskIcon({ type }: { type: string }) {
  switch (type) {
    case "task_ok":
      return <CheckCircle2 className="h-3 w-3 text-emerald-500 shrink-0" />;
    case "task_failed":
    case "host_unreachable":
      return <XC className="h-3 w-3 text-red-400 shrink-0" />;
    case "task_skipped":
      return <MinusCircle className="h-3 w-3 text-zinc-600 shrink-0" />;
    case "task_start":
    case "play_start":
      return <Circle className="h-3 w-3 text-blue-400 shrink-0 animate-pulse" />;
    default:
      return <Circle className="h-3 w-3 text-zinc-600 shrink-0" />;
  }
}

function formatLiveEvent(data: Record<string, unknown>): string {
  if (data.source === "log_file") {
    const file = (data.file as string) || "log";
    const content = (data.content as string) || "";
    const lastLine = content.split("\n").filter(Boolean).pop() || "";
    const short = lastLine.length > 120 ? lastLine.slice(0, 117) + "..." : lastLine;
    return `[${file}] ${short}`;
  }

  const type = data.type as string;
  const task = (data.task as string) || "";
  const host = (data.host as string) || "";
  const changed = data.changed as boolean;

  if (type === "play_start") return (data.play as string) || "Play starting";
  if (type === "task_start") return task || "Task starting";
  if (type === "task_ok") {
    const label = changed ? "changed" : "ok";
    return host ? `${task} (${host}) — ${label}` : `${task} — ${label}`;
  }
  if (type === "task_failed") {
    const err = (data.error as string) || "failed";
    const short = err.length > 80 ? err.slice(0, 77) + "..." : err;
    return host ? `${task} (${host}) FAILED: ${short}` : `${task} FAILED: ${short}`;
  }
  if (type === "task_skipped") return host ? `${task} (${host}) — skipped` : `${task} — skipped`;
  if (type === "host_unreachable") return `${host || "host"} — unreachable`;
  if (type === "stats") return "Playbook finished";
  return task || "...";
}

function LiveActivityStatus({ events }: { events: AgentEvent[] }) {
  const stepCount = events.filter((e) => e.event === "step_start").length;
  const toolCalls = events.filter((e) => e.event === "tool_call").length;

  const lastTool = [...events].reverse().find((e) => e.event === "tool_call");
  const lastProgress = [...events].reverse().find((e) => e.event === "progress");
  const lastApprovalGranted = [...events].reverse().find((e) => e.event === "approval_granted");

  const activeTool = lastTool ? friendlyToolName((lastTool.data.tool as string) || "") : null;
  const statusMsg = lastProgress ? (lastProgress.data.message as string) : null;

  const recentLiveLogs = useMemo(() => {
    const logs = events.filter((e) => e.event === "live_log");
    return logs.slice(-5);
  }, [events]);

  const justResumed =
    lastApprovalGranted &&
    (!lastTool || lastApprovalGranted.timestamp > lastTool.timestamp) &&
    (!lastProgress || lastApprovalGranted.timestamp > lastProgress.timestamp);

  const hasAnyInfo = stepCount > 0 || toolCalls > 0 || activeTool || statusMsg;
  const hasLiveLogs = recentLiveLogs.length > 0;

  return (
    <div className="rounded-lg border border-emerald-900/40 bg-black/50 px-3 py-2 font-mono" role="status" aria-live="polite">
      <div className="flex items-center gap-2">
        <Loader2 className="h-3 w-3 text-emerald-600 animate-spin shrink-0" />
        <div className="flex items-center gap-1.5 text-[10px] text-emerald-700 min-w-0">
          {!hasAnyInfo && <span className="text-emerald-500">Agent is thinking...</span>}
          {justResumed && hasAnyInfo && <span className="text-emerald-500">Resuming...</span>}
          {!justResumed && stepCount > 0 && (
            <>
              <span>step {stepCount}</span>
              {toolCalls > 0 && <span className="text-emerald-900">·</span>}
            </>
          )}
          {!justResumed && toolCalls > 0 && <span>{toolCalls} tool calls</span>}
          {!justResumed && activeTool && (
            <>
              <span className="text-emerald-900">·</span>
              <span className="text-emerald-500 truncate">{activeTool}</span>
            </>
          )}
        </div>
      </div>
      {!justResumed && statusMsg && !hasLiveLogs && (
        <div className="mt-1 text-[11px] text-emerald-600/80 truncate pl-5">
          {statusMsg}
        </div>
      )}
      {hasLiveLogs && (
        <div className="mt-1.5 space-y-0.5 pl-1">
          {recentLiveLogs.map((ev) => (
            <div key={ev.id} className="flex items-center gap-1.5 text-[10px] min-w-0">
              <LiveTaskIcon type={ev.data.type as string} />
              <span className={
                (ev.data.type as string) === "task_failed" || (ev.data.type as string) === "host_unreachable"
                  ? "text-red-400 truncate"
                  : (ev.data.type as string) === "task_skipped"
                    ? "text-zinc-600 truncate"
                    : (ev.data.type as string) === "play_start" || (ev.data.type as string) === "task_start"
                      ? "text-blue-400 truncate"
                      : "text-emerald-600 truncate"
              }>
                {formatLiveEvent(ev.data)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SessionCompletedBanner({ events }: { events: AgentEvent[] }) {
  const stepCount = events.filter((e) => e.event === "step_start").length;
  const toolCalls = events.filter((e) => e.event === "tool_call").length;
  const hasError = events.some(
    (e) => e.event === "error_recovery" || (e.event === "tool_result" && e.data.status === "error"),
  );

  return (
    <div className="rounded-lg border border-emerald-900/30 bg-emerald-950/20 px-3 py-2 font-mono">
      <div className="flex items-center gap-2">
        <CheckCircle2 className={`h-3 w-3 shrink-0 ${hasError ? "text-amber-500" : "text-emerald-500"}`} />
        <span className="text-[10px] text-emerald-600">
          {hasError ? "Task completed with issues" : "Task completed"}
          {stepCount > 0 && <span className="text-emerald-700 ml-1.5">· {stepCount} steps · {toolCalls} tool calls</span>}
        </span>
      </div>
    </div>
  );
}

function SessionErrorBanner({ events }: { events: AgentEvent[] }) {
  const lastError = [...events].reverse().find((e) => e.event === "error_recovery");
  const errorMsg = lastError
    ? (lastError.data.error as string) || "An unexpected error occurred."
    : "Something went wrong. Try sending a new message.";

  return (
    <div className="rounded-lg border border-red-900/40 bg-red-950/20 px-3 py-2 font-mono">
      <div className="flex items-center gap-2">
        <WifiOff className="h-3 w-3 text-red-500 shrink-0" />
        <span className="text-[10px] text-red-400 truncate">{errorMsg}</span>
      </div>
    </div>
  );
}

interface ActivityFeedProps {
  events: AgentEvent[];
  isStreaming: boolean;
  sessionStatus: Session["status"];
  isPendingApproval: boolean;
  onApprove: () => void;
  onReject: () => void;
  onQuickAction?: (prompt: string) => void;
  onCancelSecret?: () => void;
}

function PinnedMessage({
  event,
  onScrollTo,
}: {
  event: AgentEvent;
  onScrollTo: () => void;
}) {
  const content = (event.data.content as string) || "";
  const preview =
    content.length > 280 ? content.slice(0, 280) + "…" : content;
  return (
    <div className="border-t border-emerald-800/30 bg-zinc-950/95 backdrop-blur-md px-4 py-3 shadow-[0_-4px_24px_-6px_rgba(0,0,0,0.5)]">
      <button
        onClick={onScrollTo}
        className="flex w-full items-start gap-2.5 text-left group"
      >
        <MessageSquare className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500/60" />
        <div className="flex-1 min-w-0">
          <div className="text-[10px] font-medium uppercase tracking-wider text-emerald-500/50 mb-0.5">
            Latest response
          </div>
          <div className="text-xs text-zinc-300 whitespace-pre-wrap leading-relaxed line-clamp-3">
            {preview}
          </div>
        </div>
        <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-zinc-600 group-hover:text-zinc-400 transition-colors" />
      </button>
    </div>
  );
}

export function ActivityFeed({
  events,
  isStreaming,
  sessionStatus,
  isPendingApproval,
  onApprove,
  onReject,
  onQuickAction,
  onCancelSecret,
}: ActivityFeedProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const isAutoScrolling = useRef(false);
  const lastMsgRef = useRef<HTMLDivElement>(null);
  const [msgOffScreen, setMsgOffScreen] = useState(false);

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

  useEffect(() => {
    const container = containerRef.current;
    const target = lastMsgRef.current;
    if (!container || !target) {
      setMsgOffScreen(false);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => setMsgOffScreen(!entry.isIntersecting),
      { root: container, threshold: 0.1 },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [events]);

  const showActivityTicker = useMemo(() => {
    const terminalStates = new Set(["completed", "error", "rejected"]);
    if (terminalStates.has(sessionStatus)) return false;

    const waitingStates = new Set(["awaiting_approval", "awaiting_secret"]);
    if (waitingStates.has(sessionStatus)) return false;

    if (isStreaming) return true;

    if (events.length === 0) return false;
    const lastEvent = events[events.length - 1];
    const midExecTypes = new Set([
      "tool_call", "step_start", "tool_result", "progress",
      "live_log", "approval_granted", "checkpoint",
    ]);
    return midExecTypes.has(lastEvent.event);
  }, [isStreaming, events, sessionStatus]);

  const scrollToMessage = useCallback(() => {
    lastMsgRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  const grouped = useMemo(() => groupEventsIntoSteps(events), [events]);

  const approvalResolutions = useMemo(() => {
    let approvalIdx = 0;
    const resolved = new Map<number, "approved" | "rejected">();
    const approvalIndices: number[] = [];
    for (const e of events) {
      if (e.event === "approval_required") approvalIndices.push(approvalIdx++);
      if (e.event === "approval_granted") {
        const pending = approvalIndices.find((i) => !resolved.has(i));
        if (pending !== undefined) resolved.set(pending, "approved");
      }
      if (e.event === "approval_rejected") {
        const pending = approvalIndices.find((i) => !resolved.has(i));
        if (pending !== undefined) resolved.set(pending, "rejected");
      }
    }
    return resolved;
  }, [events]);

  const secretResolutions = useMemo(() => {
    let secretIdx = 0;
    const resolved = new Map<number, "provided" | "skipped">();
    const indices: number[] = [];
    for (const e of events) {
      if (e.event === "secret_request") indices.push(secretIdx++);
      if (e.event === "tool_result" && (e.data.tool as string) === "request_secret") {
        const pending = indices.find((i) => !resolved.has(i));
        if (pending !== undefined) {
          const status = (e.data.status as string) === "success" ? "provided" : "skipped";
          resolved.set(pending, status as "provided" | "skipped");
        }
      }
    }
    return resolved;
  }, [events]);

  if (events.length === 0 && !isStreaming) {
    return <EmptyState onAction={onQuickAction || (() => {})} />;
  }

  const renderItems: React.ReactNode[] = [];
  let lastMessageEvent: AgentEvent | null = null;
  let lastMessageId: string | null = null;
  let hasItemsAfterLastMessage = false;
  let approvalCounter = 0;
  let pendingApprovalGroup: { renderIdx: number; approved: number; rejected: number; lastIdx: number } | null = null;
  let secretCounter = 0;

  for (let idx = 0; idx < grouped.length; idx++) {
    const item = grouped[idx];

    if (isStepGroup(item)) continue;

    const event = item;
    if (event.event !== "approval_required") pendingApprovalGroup = null;
    switch (event.event) {
      case "user_message":
        renderItems.push(<UserMessageEvent key={event.id} event={event} />);
        lastMessageEvent = null;
        lastMessageId = null;
        hasItemsAfterLastMessage = false;
        break;
      case "message":
        lastMessageEvent = event;
        lastMessageId = event.id;
        hasItemsAfterLastMessage = false;
        renderItems.push(
          <div key={event.id} ref={lastMsgRef} data-msg-id={event.id}>
            <MessageEvent event={event} />
          </div>
        );
        break;
      case "plan": {
        if (lastMessageId) hasItemsAfterLastMessage = true;
        const completedTools = events
          .filter((e) => e.event === "tool_result" && e.data.status === "success")
          .map((e) => e.data.tool as string);
        const hasLaterMessage = grouped.slice(idx + 1).some(
          (g) => !isStepGroup(g) && g.event === "message",
        );
        renderItems.push(
          <PlanEvent
            key={event.id}
            event={event}
            completedTools={completedTools}
            isStale={hasLaterMessage}
          />,
        );
        break;
      }
      case "secret_request": {
        const thisSecretIdx = secretCounter++;
        const resolution = secretResolutions.get(thisSecretIdx);
        if (resolution) {
          const secretName = (event.data.secret_name as string) || "secret";
          const wasProvided = resolution === "provided";
          renderItems.push(
            <div key={event.id} className={`flex items-center gap-2 rounded-md border px-3 py-1.5 bg-zinc-900/40 ${wasProvided ? "border-emerald-800/20" : "border-zinc-800/40"}`}>
              <CheckCircle2 className={`h-3.5 w-3.5 ${wasProvided ? "text-emerald-400" : "text-zinc-500"}`} />
              <span className={`text-xs font-medium ${wasProvided ? "text-emerald-400" : "text-zinc-500"}`}>
                {wasProvided ? "Secret stored" : "Secret skipped"}
              </span>
              <code className={`rounded px-1.5 py-0.5 text-[10px] font-mono ${wasProvided ? "bg-emerald-900/30 text-emerald-500/80" : "bg-zinc-800/60 text-zinc-600"}`}>{secretName}</code>
            </div>,
          );
        } else {
          if (lastMessageId) hasItemsAfterLastMessage = true;
          renderItems.push(<SecretRequestEvent key={event.id} event={event} onSkip={onCancelSecret} />);
        }
        break;
      }
      case "approval_required": {
        const thisApprovalIdx = approvalCounter++;
        const resolution = approvalResolutions.get(thisApprovalIdx);

        if (resolution) {
          if (pendingApprovalGroup) {
            pendingApprovalGroup.approved += resolution === "approved" ? 1 : 0;
            pendingApprovalGroup.rejected += resolution === "rejected" ? 1 : 0;
            pendingApprovalGroup.lastIdx = thisApprovalIdx;
            const { approved, rejected, lastIdx } = pendingApprovalGroup;
            const allRejected = approved === 0 && rejected > 0;
            renderItems[pendingApprovalGroup.renderIdx] = (
              <div key={`approval-group-${lastIdx}`}
                className={`flex items-center gap-2 rounded-md border px-3 py-1.5 bg-zinc-900/40 ${allRejected ? "border-red-800/20" : "border-emerald-800/20"}`}>
                {allRejected
                  ? <XC className="h-3.5 w-3.5 text-red-400" />
                  : <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />}
                {approved > 0 && <span className="text-xs font-medium text-emerald-400">{approved} approved</span>}
                {rejected > 0 && <span className="text-xs font-medium text-red-400">{rejected} rejected</span>}
              </div>
            );
          } else {
            pendingApprovalGroup = {
              renderIdx: renderItems.length,
              approved: resolution === "approved" ? 1 : 0,
              rejected: resolution === "rejected" ? 1 : 0,
              lastIdx: thisApprovalIdx,
            };
            renderItems.push(
              <div key={`approval-group-${thisApprovalIdx}`}
                className={`flex items-center gap-2 rounded-md border px-3 py-1.5 bg-zinc-900/40 ${resolution === "rejected" ? "border-red-800/20" : "border-emerald-800/20"}`}>
                {resolution === "rejected"
                  ? <XC className="h-3.5 w-3.5 text-red-400" />
                  : <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />}
                <span className={`text-xs font-medium ${resolution === "rejected" ? "text-red-400" : "text-emerald-400"}`}>
                  {resolution === "rejected" ? "Rejected" : "Approved"}
                </span>
              </div>,
            );
          }
        } else {
          pendingApprovalGroup = null;
          if (lastMessageId) hasItemsAfterLastMessage = true;
          renderItems.push(
            <DiffReview
              key={event.id}
              event={event}
              isPending={isPendingApproval}
              onApprove={onApprove}
              onReject={onReject}
            />
          );
        }
        break;
      }
      case "max_steps":
        if (lastMessageId) hasItemsAfterLastMessage = true;
        renderItems.push(<ErrorEvent key={event.id} event={event} />);
        break;
      case "error_recovery":
        if (lastMessageId) hasItemsAfterLastMessage = true;
        renderItems.push(
          <div key={event.id} className="rounded-lg border border-amber-900/40 bg-amber-950/20 px-3 py-2 font-mono">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-3 w-3 text-amber-500 shrink-0" />
              <span className="text-[10px] text-amber-400 truncate">
                {(event.data.error as string) || "An internal error occurred — the agent is recovering."}
              </span>
            </div>
          </div>
        );
        break;
      default:
        break;
    }
  }

  const showPinned =
    msgOffScreen && hasItemsAfterLastMessage && lastMessageEvent != null;

  const statusBar = showActivityTicker ? (
    <LiveActivityStatus events={events} />
  ) : sessionStatus === "completed" && events.length > 0 ? (
    <SessionCompletedBanner events={events} />
  ) : sessionStatus === "error" && events.length > 0 ? (
    <SessionErrorBanner events={events} />
  ) : null;

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-4 py-3 space-y-3"
      >
        {renderItems}
      </div>
      {showPinned && (
        <PinnedMessage
          event={lastMessageEvent!}
          onScrollTo={scrollToMessage}
        />
      )}
      {statusBar && (
        <div className="shrink-0 border-t border-zinc-800/50 px-4 py-2">
          {statusBar}
        </div>
      )}
      <UsageBadge events={events} />
    </div>
  );
}

function UsageBadge({ events }: { events: AgentEvent[] }) {
  const usage = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i--) {
      if (events[i].event === "usage") return events[i].data;
    }
    return null;
  }, [events]);

  if (!usage) return null;

  const tokens = (usage.total_tokens as number) || 0;
  const cost = (usage.estimated_cost as number) || 0;
  const fmt = tokens >= 1000 ? `${(tokens / 1000).toFixed(1)}k` : String(tokens);
  const costFmt = cost > 0 ? `$${cost < 0.01 ? cost.toFixed(4) : cost.toFixed(2)}` : null;

  return (
    <div className="shrink-0 flex items-center justify-end gap-3 px-4 py-1 border-t border-zinc-800/30 text-[10px] text-zinc-600">
      <span>{fmt} tokens</span>
      {costFmt && <span>{costFmt}</span>}
    </div>
  );
}
