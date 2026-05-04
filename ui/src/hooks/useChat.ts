import { useCallback, useEffect, useRef, useState } from "react";
import { streamChat, reconnectStream, getLastSeq, clearLastSeq, api } from "@/api/client";
import type { AgentEvent, Session, WorkspaceFile } from "@/api/types";

interface UseChatOptions {
  addEvent: (sessionId: string, event: AgentEvent) => void;
  updateStatus: (sessionId: string, status: Session["status"]) => void;
  updateSessionId: (oldId: string, newId: string) => void;
  setPlaybooks: (sessionId: string, playbooks: Record<string, string>) => void;
  setInventory: (sessionId: string, inventory: Record<string, string>) => void;
  setWorkspaceFiles: (sessionId: string, files: WorkspaceFile[]) => void;
}

interface PerSessionState {
  serverSid: string | null;
  controller: AbortController | null;
  streaming: boolean;
  reconnectAttempts: number;
  reconnectTimer: ReturnType<typeof setTimeout> | null;
}

const sessionStates = new Map<string, PerSessionState>();

const MAX_RECONNECT_ATTEMPTS = 15;
const BASE_BACKOFF_MS = 1_000;

function getSessionState(id: string): PerSessionState {
  let s = sessionStates.get(id);
  if (!s) {
    const isServerSid = id && !id.startsWith("local-");
    s = {
      serverSid: isServerSid ? id : null,
      controller: null,
      streaming: false,
      reconnectAttempts: 0,
      reconnectTimer: null,
    };
    sessionStates.set(id, s);
  }
  return s;
}

export function useChat(opts: UseChatOptions & { activeSessionId?: string }) {
  const [streamingSet, setStreamingSet] = useState<Set<string>>(new Set());
  const forceUpdate = useRef(0);

  const activeId = opts.activeSessionId ?? "";
  const isStreaming = streamingSet.has(activeId);

  const markStreaming = useCallback((sid: string, on: boolean) => {
    setStreamingSet((prev) => {
      const next = new Set(prev);
      if (on) next.add(sid); else next.delete(sid);
      return next;
    });
    const ss = getSessionState(sid);
    ss.streaming = on;
  }, []);

  const handleEvent = useCallback(
    (sessionId: string, ss: PerSessionState, event: AgentEvent) => {
      if (event.event === "session_started" && event.data?.session_id) {
        ss.serverSid = event.data.session_id as string;
        return;
      }
      opts.addEvent(sessionId, event);

      switch (event.event) {
        case "approval_required":
          opts.updateStatus(sessionId, "awaiting_approval");
          markStreaming(sessionId, false);
          break;
        case "secret_request":
          opts.updateStatus(sessionId, "awaiting_secret");
          markStreaming(sessionId, false);
          break;
        case "approval_granted":
          opts.updateStatus(sessionId, "active");
          markStreaming(sessionId, true);
          break;
        case "approval_rejected":
          markStreaming(sessionId, true);
          break;
        case "step_start":
        case "tool_call":
        case "tool_result":
        case "progress":
        case "message":
        case "plan":
          opts.updateStatus(sessionId, "active");
          markStreaming(sessionId, true);
          break;
        default:
          break;
      }
    },
    [opts, markStreaming],
  );

  const finishSession = useCallback(
    async (sessionId: string, ss: PerSessionState, returnedSessionId: string, backendStatus?: string) => {
      ss.serverSid = returnedSessionId;
      ss.reconnectAttempts = 0;
      opts.updateSessionId(sessionId, returnedSessionId);

      const newSs = getSessionState(returnedSessionId);
      newSs.serverSid = returnedSessionId;
      newSs.controller = ss.controller;

      if (sessionId !== returnedSessionId) {
        sessionStates.delete(sessionId);
        clearLastSeq(sessionId);
      }

      const resolvedStatus = (backendStatus || "completed") as Session["status"];
      markStreaming(sessionId, false);
      markStreaming(returnedSessionId, false);
      opts.updateStatus(sessionId, resolvedStatus);
      opts.updateStatus(returnedSessionId, resolvedStatus);

      try {
        const pb = await api.playbooks(returnedSessionId);
        opts.setPlaybooks(returnedSessionId, pb.playbooks);
      } catch { /* session may have been cleaned up */ }

      try {
        const inv = await api.inventory(returnedSessionId);
        opts.setInventory(returnedSessionId, inv.inventory_files);
      } catch { /* ignore */ }

      try {
        const ws = await api.workspaceFiles(returnedSessionId);
        opts.setWorkspaceFiles(returnedSessionId, ws.files);
      } catch { /* ignore */ }
    },
    [opts, markStreaming],
  );

  const tryReconnect = useCallback(
    (sessionId: string) => {
      const ss = getSessionState(sessionId);
      const sid = ss.serverSid || sessionId;

      if (ss.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
        opts.addEvent(sessionId, {
          id: `err-${Date.now()}`,
          event: "error_recovery",
          data: { error: "Connection lost after multiple retries. Check the agent status or try sending a new message." },
          timestamp: Date.now(),
        });
        markStreaming(sessionId, false);
        opts.updateStatus(sessionId, "error");
        return;
      }

      const delay = BASE_BACKOFF_MS * Math.pow(2, ss.reconnectAttempts);
      ss.reconnectAttempts += 1;

      ss.reconnectTimer = setTimeout(async () => {
        let sessionDone = false;
        let lastKnownStatus = "completed";
        try {
          const statusResp = await api.sessionStatus(sid);
          lastKnownStatus = statusResp.status;
          sessionDone = ["completed", "error", "max_steps_reached", "rejected"].includes(lastKnownStatus);
        } catch {
          markStreaming(sessionId, false);
          opts.updateStatus(sessionId, "error");
          return;
        }

        markStreaming(sessionId, true);
        opts.updateStatus(sessionId, "active");

        const controller = reconnectStream(
          sid,
          getLastSeq(sid),
          (event) => {
            ss.reconnectAttempts = 0;
            handleEvent(sessionId, ss, event);
          },
          async (doneStatus) => {
            ss.reconnectAttempts = 0;
            await finishSession(sessionId, ss, sid, doneStatus);
          },
          () => {
            if (sessionDone) {
              finishSession(sessionId, ss, sid, lastKnownStatus);
            } else {
              tryReconnect(sessionId);
            }
          },
        );
        ss.controller = controller;
      }, delay);
    },
    [opts, markStreaming, handleEvent, finishSession],
  );

  const send = useCallback(
    (message: string, sessionId: string, projectPath?: string) => {
      const ss = getSessionState(sessionId);
      if (ss.streaming) return;

      ss.controller?.abort();
      if (ss.reconnectTimer) {
        clearTimeout(ss.reconnectTimer);
        ss.reconnectTimer = null;
      }

      markStreaming(sessionId, true);
      opts.updateStatus(sessionId, "active");
      ss.reconnectAttempts = 0;

      opts.addEvent(sessionId, {
        id: `usr-${Date.now()}`,
        event: "user_message",
        data: { content: message },
        timestamp: Date.now(),
      });

      const controller = streamChat(
        message,
        ss.serverSid,
        (event) => handleEvent(sessionId, ss, event),
        (error) => {
          opts.addEvent(sessionId, {
            id: `err-${Date.now()}`,
            event: "error_recovery",
            data: { error: error.message },
            timestamp: Date.now(),
          });
          opts.updateStatus(sessionId, "error");
          markStreaming(sessionId, false);
        },
        async (returnedSessionId, doneStatus) => finishSession(sessionId, ss, returnedSessionId, doneStatus),
        () => tryReconnect(sessionId),
        projectPath,
      );

      ss.controller = controller;
    },
    [opts, markStreaming, handleEvent, finishSession, tryReconnect],
  );

  const approve = useCallback(
    async (sessionId: string) => {
      const ss = getSessionState(sessionId);
      const sid = ss.serverSid || sessionId;
      try {
        await api.approve(sid);
        opts.updateStatus(sessionId, "active");
        markStreaming(sessionId, true);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        opts.addEvent(sessionId, {
          id: `err-${Date.now()}`,
          event: "error_recovery",
          data: { error: `Approval failed: ${msg}. Try sending a new message.` },
          timestamp: Date.now(),
        });
        opts.updateStatus(sessionId, "error");
        markStreaming(sessionId, false);
      }
    },
    [opts, markStreaming]
  );

  const reject = useCallback(
    async (sessionId: string, feedback = "") => {
      const ss = getSessionState(sessionId);
      const sid = ss.serverSid || sessionId;
      try {
        await api.reject(sid, feedback);
        opts.updateStatus(sessionId, "rejected");
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        opts.addEvent(sessionId, {
          id: `err-${Date.now()}`,
          event: "error_recovery",
          data: { error: `Rejection failed: ${msg}` },
          timestamp: Date.now(),
        });
        opts.updateStatus(sessionId, "error");
        markStreaming(sessionId, false);
      }
    },
    [opts, markStreaming]
  );

  const cancel = useCallback(() => {
    const ss = getSessionState(activeId);
    ss.controller?.abort();
    if (ss.reconnectTimer) {
      clearTimeout(ss.reconnectTimer);
      ss.reconnectTimer = null;
    }
    markStreaming(activeId, false);
  }, [activeId, markStreaming]);

  const cleanupSession = useCallback((sessionId: string) => {
    const ss = sessionStates.get(sessionId);
    if (ss) {
      ss.controller?.abort();
      if (ss.reconnectTimer) clearTimeout(ss.reconnectTimer);
      sessionStates.delete(sessionId);
    }
    clearLastSeq(sessionId);
  }, []);

  useEffect(() => {
    return () => {
      for (const [, ss] of sessionStates) {
        ss.controller?.abort();
        ss.streaming = false;
        if (ss.reconnectTimer) clearTimeout(ss.reconnectTimer);
      }
    };
  }, []);

  return { send, approve, reject, cancel, cleanupSession, isStreaming };
}
