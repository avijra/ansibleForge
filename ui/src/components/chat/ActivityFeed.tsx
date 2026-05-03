import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { CheckCircle2, ChevronDown, ChevronRight, KeyRound, ShieldCheck, XCircle, Layers, MessageSquare } from "lucide-react";
import type { AgentEvent } from "@/api/types";
import { api } from "@/api/client";
import { TuyereThinkingIndicator } from "@/components/common/TuyereLogo";
import { friendlyToolName } from "@/lib/tool-labels";
import { ThinkingEvent } from "./events/ThinkingEvent";
import { ToolCallEvent } from "./events/ToolCallEvent";
import { ToolResultEvent } from "./events/ToolResultEvent";
import { DiffReview } from "@/components/review/DiffReview";
import { MessageEvent } from "./events/MessageEvent";
import { ErrorEvent } from "./events/ErrorEvent";
import { PlanEvent } from "./events/PlanEvent";
import { UserMessageEvent } from "./events/UserMessageEvent";
import { SecretRequestEvent } from "./events/SecretRequestEvent";
import { EmptyState } from "./EmptyState";
import { cn } from "@/lib/utils";

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
    "secret_request", "approval_required",
  ]);

  const STEP_EVENTS = new Set([
    "step_start", "thinking", "tool_call", "tool_result",
    "progress", "checkpoint", "error_recovery",
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

function StepSummaryLine({ group, onClick }: { group: StepGroup; onClick?: () => void }) {
  const isSecret = group.stepNum <= -1000 && group.stepNum > -2000;
  const isApproval = group.stepNum <= -2000;

  let Icon = group.status === "error" ? XCircle : CheckCircle2;
  let iconColor = group.status === "error" ? "text-red-400/60" : "text-emerald-400/50";
  if (isSecret) { Icon = KeyRound; iconColor = "text-cyan-400/60"; }
  if (isApproval) { Icon = ShieldCheck; iconColor = group.status === "error" ? "text-red-400/60" : "text-emerald-400/50"; }

  const label = group.toolSummary || `Step ${group.stepNum}`;

  return (
    <button
      onClick={onClick}
      className="flex w-full items-center gap-2 py-0.5 text-left group"
    >
      <Icon className={cn("h-3 w-3 shrink-0", iconColor)} />
      <span className="text-[11px] text-zinc-500 truncate flex-1 group-hover:text-zinc-300 transition-colors">
        {label}
      </span>
    </button>
  );
}

function CollapsedStepsBlock({ groups }: { groups: StepGroup[] }) {
  const [expanded, setExpanded] = useState(false);
  const [expandedStep, setExpandedStep] = useState<number | null>(null);
  const errorCount = groups.filter((g) => g.status === "error").length;
  const totalTools = groups.reduce(
    (sum, g) => sum + g.events.filter((e) => e.event === "tool_call").length,
    0
  );

  if (groups.length === 1) {
    return (
      <div className="rounded-lg border border-zinc-800/40 bg-zinc-900/20">
        <div className="px-3 py-1.5">
          <StepSummaryLine
            group={groups[0]}
            onClick={() => setExpandedStep(expandedStep === 0 ? null : 0)}
          />
        </div>
        {expandedStep === 0 && (
          <div className="px-3 pb-2 pt-1 space-y-2 border-t border-zinc-800/30">
            {groups[0].events.map((event) => (
              <StepEventRenderer key={event.id} event={event} />
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-zinc-800/40 bg-zinc-900/20">
      <button
        onClick={() => { setExpanded(!expanded); setExpandedStep(null); }}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-zinc-800/20 transition-colors rounded-lg"
      >
        <Layers className="h-3 w-3 text-zinc-600 shrink-0" />
        <span className="text-[11px] text-zinc-500 flex-1">
          {groups.length} steps completed
          {totalTools > 0 && <span className="text-zinc-600"> · {totalTools} tool calls</span>}
          {errorCount > 0 && <span className="text-red-400/60"> · {errorCount} failed</span>}
        </span>
        {expanded
          ? <ChevronDown className="h-3 w-3 text-zinc-600 shrink-0" />
          : <ChevronRight className="h-3 w-3 text-zinc-600 shrink-0" />}
      </button>
      {expanded && (
        <div className="px-3 pb-2 space-y-0.5 border-t border-zinc-800/30 pt-1">
          {groups.map((group, i) => (
            <div key={`step-${group.stepNum}-${i}`}>
              <StepSummaryLine
                group={group}
                onClick={() => setExpandedStep(expandedStep === i ? null : i)}
              />
              {expandedStep === i && (
                <div className="pl-5 pb-2 pt-1 space-y-2">
                  {group.events.map((event) => (
                    <StepEventRenderer key={event.id} event={event} />
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StepEventRenderer({ event }: { event: AgentEvent }) {
  switch (event.event) {
    case "thinking":
      return <ThinkingEvent event={event} />;
    case "tool_call":
      return <ToolCallEvent event={event} />;
    case "tool_result":
      return <ToolResultEvent event={event} />;
    case "error_recovery":
      return <ErrorEvent event={event} />;
    case "approval_granted":
      return (
        <div className="rounded-lg bg-emerald-950/15 border border-emerald-800/30 px-3 py-2 text-xs text-zinc-400">
          Approved — executing...
        </div>
      );
    case "approval_rejected":
      return (
        <div className="rounded-lg bg-zinc-900 border border-zinc-800 px-3 py-2 text-xs text-zinc-400">
          Rejected. {event.data.feedback as string}
        </div>
      );
    case "secret_request": {
      const name = (event.data.secret_name as string) || "secret";
      return (
        <div className="flex items-center gap-2 rounded-md border border-emerald-800/20 bg-zinc-900/40 px-3 py-1.5">
          <KeyRound className="h-3.5 w-3.5 text-cyan-400/60" />
          <span className="text-xs text-zinc-400">Secret provided</span>
          <code className="rounded bg-zinc-800/60 px-1.5 py-0.5 text-[10px] font-mono text-zinc-500">{name}</code>
        </div>
      );
    }
    case "approval_required": {
      const mode = (event.data.mode as string) || "";
      return (
        <div className="flex items-center gap-2 rounded-md border border-emerald-800/20 bg-zinc-900/40 px-3 py-1.5">
          <ShieldCheck className="h-3.5 w-3.5 text-emerald-400/60" />
          <span className="text-xs text-zinc-400">Approved{mode ? ` (${mode})` : ""}</span>
        </div>
      );
    }
    case "step_start":
      return null;
    case "progress":
      return (
        <div className="flex items-center gap-2.5 py-1 text-xs text-zinc-500">
          <span>{event.data.message as string}</span>
        </div>
      );
    case "checkpoint":
      return (
        <div className="flex items-center gap-2 py-1 text-[10px] font-mono text-zinc-600">
          <span className="text-zinc-500">checkpoint</span>
          <span>{event.data.hash as string}</span>
        </div>
      );
    default:
      return null;
  }
}

interface ActivityFeedProps {
  events: AgentEvent[];
  isStreaming: boolean;
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
  let collapsedBuffer: StepGroup[] = [];
  let lastMessageEvent: AgentEvent | null = null;
  let lastMessageId: string | null = null;
  let hasItemsAfterLastMessage = false;
  let approvalCounter = 0;
  let secretCounter = 0;

  const flushCollapsed = () => {
    if (collapsedBuffer.length === 0) return;
    renderItems.push(
      <CollapsedStepsBlock
        key={`collapsed-${collapsedBuffer[0].stepNum}`}
        groups={[...collapsedBuffer]}
      />
    );
    collapsedBuffer = [];
  };

  for (let idx = 0; idx < grouped.length; idx++) {
    const item = grouped[idx];

    if (isStepGroup(item)) {
      const isLast = idx === grouped.length - 1;
      if (item.isComplete && !isLast) {
        collapsedBuffer.push(item);
        continue;
      }
      flushCollapsed();
      if (lastMessageId) hasItemsAfterLastMessage = true;
      renderItems.push(
        <div key={`step-live-${item.stepNum}-${idx}`} className="space-y-3">
          {item.events.map((event) => (
            <StepEventRenderer key={event.id} event={event} />
          ))}
        </div>
      );
      continue;
    }

    const event = item;
    switch (event.event) {
      case "user_message":
        flushCollapsed();
        renderItems.push(<UserMessageEvent key={event.id} event={event} />);
        lastMessageEvent = null;
        lastMessageId = null;
        hasItemsAfterLastMessage = false;
        break;
      case "message":
        flushCollapsed();
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
        flushCollapsed();
        const completedTools = events
          .filter((e) => e.event === "tool_result" && e.data.status === "success")
          .map((e) => e.data.tool as string);
        renderItems.push(<PlanEvent key={event.id} event={event} completedTools={completedTools} />);
        break;
      }
      case "secret_request": {
        const thisSecretIdx = secretCounter++;
        const resolution = secretResolutions.get(thisSecretIdx);
        if (resolution) {
          const secretName = (event.data.secret_name as string) || "secret";
          collapsedBuffer.push({
            stepNum: -(thisSecretIdx + 1000),
            events: [event],
            isComplete: true,
            toolSummary: resolution === "provided" ? `Secret provided: ${secretName}` : `Secret skipped: ${secretName}`,
            status: "success",
          });
        } else {
          flushCollapsed();
          renderItems.push(<SecretRequestEvent key={event.id} event={event} onSkip={onCancelSecret} />);
        }
        break;
      }
      case "approval_required": {
        const thisApprovalIdx = approvalCounter++;
        const resolution = approvalResolutions.get(thisApprovalIdx);
        if (resolution) {
          const output = (event.data.output as string) || "";
          const mode = (event.data.mode as string) || "";
          const label = resolution === "approved"
            ? `Approved${mode ? ` (${mode})` : ""}`
            : `Rejected${output ? ` — ${output.slice(0, 40)}` : ""}`;
          collapsedBuffer.push({
            stepNum: -(thisApprovalIdx + 2000),
            events: [event],
            isComplete: true,
            toolSummary: label,
            status: resolution === "approved" ? "success" : "error",
          });
        } else {
          flushCollapsed();
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
        flushCollapsed();
        renderItems.push(<ErrorEvent key={event.id} event={event} />);
        break;
      default:
        flushCollapsed();
        break;
    }
  }
  flushCollapsed();

  const showPinned =
    msgOffScreen && hasItemsAfterLastMessage && lastMessageEvent != null;

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-4 py-3 space-y-3"
      >
        {renderItems}
        {isStreaming &&
          (() => {
            const lastProgress = [...events]
              .reverse()
              .find((e) => e.event === "progress");
            const msg = lastProgress
              ? (lastProgress.data.message as string)
              : "Thinking...";
            return <TuyereThinkingIndicator message={msg} />;
          })()}
      </div>
      {showPinned && (
        <PinnedMessage
          event={lastMessageEvent!}
          onScrollTo={scrollToMessage}
        />
      )}
    </div>
  );
}
