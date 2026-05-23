import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Loader2, MessageSquare, WifiOff, Circle, XCircle as XC, MinusCircle, Shield, KeyRound } from "lucide-react";
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
    case "shell_output":
      return <ChevronRight className="h-3 w-3 text-cyan-500 shrink-0" />;
    case "stderr_line":
      return <ChevronRight className="h-3 w-3 text-amber-500 shrink-0" />;
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

  if (type === "shell_output" || type === "stderr_line") {
    const line = (data.line as string) || "";
    return line.length > 120 ? line.slice(0, 117) + "..." : line;
  }
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

function useElapsedTimer(active: boolean) {
  const startRef = useRef(Date.now());
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!active) {
      startRef.current = Date.now();
      setElapsed(0);
      return;
    }
    startRef.current = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - startRef.current) / 1000)), 1000);
    return () => clearInterval(id);
  }, [active]);

  return elapsed;
}

function formatElapsed(secs: number): string {
  if (secs < 60) return `${secs}s`;
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

function liveLogColor(type: string): string {
  if (type === "task_failed" || type === "host_unreachable") return "text-red-400 truncate";
  if (type === "task_skipped") return "text-zinc-600 truncate";
  if (type === "play_start" || type === "task_start") return "text-blue-400 truncate";
  if (type === "shell_output") return "text-cyan-400/80 truncate font-mono";
  if (type === "stderr_line") return "text-amber-400/80 truncate font-mono";
  return "text-emerald-600 truncate";
}

function LiveActivityStatus({ events }: { events: AgentEvent[] }) {
  const stepCount = events.filter((e) => e.event === "step_start").length;
  const toolCalls = events.filter((e) => e.event === "tool_call").length;

  const lastTool = [...events].reverse().find((e) => e.event === "tool_call");
  const lastProgress = [...events].reverse().find((e) => e.event === "progress");
  const lastApprovalGranted = [...events].reverse().find((e) => e.event === "approval_granted");

  const activeTool = lastTool ? friendlyToolName((lastTool.data.tool as string) || "") : null;
  const statusMsg = lastProgress ? (lastProgress.data.message as string) : null;

  const progressElapsed = lastProgress ? (lastProgress.data.elapsed_seconds as number) || 0 : 0;
  const isLongRunning = progressElapsed > 30;

  const elapsed = useElapsedTimer(!!lastTool);

  const recentLiveLogs = useMemo(() => {
    const logs = events.filter((e) => e.event === "live_log");
    return logs.slice(-8);
  }, [events]);

  const justResumed =
    lastApprovalGranted &&
    (!lastTool || lastApprovalGranted.timestamp > lastTool.timestamp) &&
    (!lastProgress || lastApprovalGranted.timestamp > lastProgress.timestamp);

  const hasAnyInfo = stepCount > 0 || toolCalls > 0 || activeTool || statusMsg;
  const hasLiveLogs = recentLiveLogs.length > 0;

  const borderColor = isLongRunning ? "border-cyan-800/60" : "border-emerald-900/40";
  const bgColor = isLongRunning ? "bg-cyan-950/30" : "bg-black/50";

  return (
    <div className={`rounded-lg border ${borderColor} ${bgColor} px-3 py-2 font-mono`} role="status" aria-live="polite">
      <div className="flex items-center gap-2">
        <Loader2 className={`h-3.5 w-3.5 animate-spin shrink-0 ${isLongRunning ? "text-cyan-500" : "text-emerald-600"}`} />
        <div className="flex items-center gap-1.5 text-[10px] text-emerald-700 min-w-0 flex-1">
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
              <span className={`truncate ${isLongRunning ? "text-cyan-400" : "text-emerald-500"}`}>{activeTool}</span>
            </>
          )}
        </div>
        {elapsed > 10 && (
          <span className={`text-[10px] tabular-nums shrink-0 ${isLongRunning ? "text-cyan-500/70" : "text-emerald-700/50"}`}>
            {formatElapsed(elapsed)}
          </span>
        )}
      </div>
      {!justResumed && statusMsg && !hasLiveLogs && (
        <div className={`mt-1 text-[11px] truncate pl-5 ${isLongRunning ? "text-cyan-400/60" : "text-emerald-600/80"}`}>
          {statusMsg}
        </div>
      )}
      {hasLiveLogs && (
        <div className="mt-1.5 space-y-0.5 pl-1 max-h-[120px] overflow-y-auto">
          {recentLiveLogs.map((ev) => (
            <div key={ev.id} className="flex items-center gap-1.5 text-[10px] min-w-0">
              <LiveTaskIcon type={ev.data.type as string} />
              <span className={liveLogColor(ev.data.type as string)}>
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

function CollapsedSystemBadge({
  approved,
  rejected,
  storedSecrets,
  skippedSecrets,
  allRejected,
}: {
  approved: number;
  rejected: number;
  storedSecrets: string[];
  skippedSecrets: string[];
  allRejected: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const hasApprovals = approved > 0 || rejected > 0;
  const hasSecrets = storedSecrets.length > 0 || skippedSecrets.length > 0;
  if (!hasApprovals && !hasSecrets) return null;

  const borderColor = allRejected ? "border-red-800/20" : "border-emerald-800/20";
  const Icon = allRejected ? XC : CheckCircle2;
  const iconColor = allRejected ? "text-red-400" : "text-emerald-400";

  const parts: string[] = [];
  if (approved > 0) parts.push(`${approved} approved`);
  if (rejected > 0) parts.push(`${rejected} rejected`);
  if (storedSecrets.length > 0) parts.push(`${storedSecrets.length} secret${storedSecrets.length > 1 ? "s" : ""} stored`);
  if (skippedSecrets.length > 0) parts.push(`${skippedSecrets.length} skipped`);
  const summary = parts.join(" · ");

  const hasDetails = storedSecrets.length > 0 || skippedSecrets.length > 0;

  return (
    <div className={`rounded-md border bg-zinc-900/40 ${borderColor}`}>
      <button
        onClick={() => hasDetails && setExpanded(!expanded)}
        className={`flex w-full items-center gap-2 px-3 py-1.5 text-left ${hasDetails ? "cursor-pointer" : "cursor-default"}`}
      >
        <Icon className={`h-3.5 w-3.5 shrink-0 ${iconColor}`} />
        {hasApprovals && <Shield className="h-3 w-3 shrink-0 text-zinc-600" />}
        {hasSecrets && <KeyRound className="h-3 w-3 shrink-0 text-zinc-600" />}
        <span className="text-xs text-zinc-400 flex-1">{summary}</span>
        {hasDetails && (
          expanded
            ? <ChevronDown className="h-3 w-3 text-zinc-600 shrink-0" />
            : <ChevronRight className="h-3 w-3 text-zinc-600 shrink-0" />
        )}
      </button>
      {expanded && (
        <div className="border-t border-zinc-800/30 px-3 py-1.5 space-y-0.5">
          {storedSecrets.map((name) => (
            <div key={name} className="flex items-center gap-1.5 text-[10px]">
              <CheckCircle2 className="h-2.5 w-2.5 text-emerald-500/70 shrink-0" />
              <code className="text-emerald-500/60 font-mono">{name}</code>
            </div>
          ))}
          {skippedSecrets.map((name) => (
            <div key={name} className="flex items-center gap-1.5 text-[10px]">
              <XC className="h-2.5 w-2.5 text-zinc-600 shrink-0" />
              <code className="text-zinc-600 font-mono">{name}</code>
            </div>
          ))}
        </div>
      )}
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
  let secretCounter = 0;

  type SystemGroup = {
    renderIdx: number;
    approved: number;
    rejected: number;
    secrets: { name: string; provided: boolean }[];
    key: string;
  };
  let sysGroup: SystemGroup | null = null;

  const flushSystemGroup = () => {
    if (!sysGroup) return;
    const { approved, rejected, secrets, key } = sysGroup;
    const storedSecrets = secrets.filter((s) => s.provided);
    const skippedSecrets = secrets.filter((s) => !s.provided);
    const allRejected = approved === 0 && rejected > 0 && storedSecrets.length === 0;
    renderItems[sysGroup.renderIdx] = (
      <CollapsedSystemBadge
        key={key}
        approved={approved}
        rejected={rejected}
        storedSecrets={storedSecrets.map((s) => s.name)}
        skippedSecrets={skippedSecrets.map((s) => s.name)}
        allRejected={allRejected}
      />
    );
    sysGroup = null;
  };

  const ensureSystemGroup = () => {
    if (!sysGroup) {
      sysGroup = {
        renderIdx: renderItems.length,
        approved: 0,
        rejected: 0,
        secrets: [],
        key: `sys-${renderItems.length}`,
      };
      renderItems.push(null);
    }
  };

  for (let idx = 0; idx < grouped.length; idx++) {
    const item = grouped[idx];

    if (isStepGroup(item)) continue;

    const event = item;

    const isResolvedApproval = event.event === "approval_required" && approvalResolutions.has(approvalCounter);
    const isResolvedSecret = event.event === "secret_request" && secretResolutions.has(secretCounter);

    if (!isResolvedApproval && !isResolvedSecret) {
      flushSystemGroup();
    }

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
          ensureSystemGroup();
          sysGroup!.secrets.push({
            name: (event.data.secret_name as string) || "secret",
            provided: resolution === "provided",
          });
          flushSystemGroup();
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
          ensureSystemGroup();
          sysGroup!.approved += resolution === "approved" ? 1 : 0;
          sysGroup!.rejected += resolution === "rejected" ? 1 : 0;
        } else {
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
  flushSystemGroup();

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
    </div>
  );
}
