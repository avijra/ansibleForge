import { useCallback, useRef, useState } from "react";
import { streamChat, api } from "@/api/client";
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
}

const sessionStates = new Map<string, PerSessionState>();

function getSessionState(id: string): PerSessionState {
  let s = sessionStates.get(id);
  if (!s) {
    const isServerSid = id && !id.startsWith("local-");
    s = { serverSid: isServerSid ? id : null, controller: null, streaming: false };
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

  const send = useCallback(
    (message: string, sessionId: string, projectPath?: string) => {
      const ss = getSessionState(sessionId);
      if (ss.streaming) return;
      markStreaming(sessionId, true);
      opts.updateStatus(sessionId, "active");

      opts.addEvent(sessionId, {
        id: `usr-${Date.now()}`,
        event: "user_message",
        data: { content: message },
        timestamp: Date.now(),
      });

      const controller = streamChat(
        message,
        ss.serverSid,
        (event) => {
          if (
            event.event === "session_started" &&
            event.data?.session_id
          ) {
            ss.serverSid = event.data.session_id as string;
            return;
          }

          opts.addEvent(sessionId, event);

          if (event.event === "approval_required") {
            opts.updateStatus(sessionId, "awaiting_approval");
            markStreaming(sessionId, false);
          }
          if (event.event === "secret_request") {
            opts.updateStatus(sessionId, "awaiting_secret");
            markStreaming(sessionId, false);
          }
          if (event.event === "approval_granted") {
            opts.updateStatus(sessionId, "active");
            markStreaming(sessionId, true);
          }
        },
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
        async (returnedSessionId) => {
          ss.serverSid = returnedSessionId;
          opts.updateSessionId(sessionId, returnedSessionId);

          const newSs = getSessionState(returnedSessionId);
          newSs.serverSid = returnedSessionId;
          newSs.controller = ss.controller;

          markStreaming(sessionId, false);
          markStreaming(returnedSessionId, false);
          opts.updateStatus(sessionId, "completed");
          opts.updateStatus(returnedSessionId, "completed");

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
        projectPath,
      );

      ss.controller = controller;
    },
    [opts, markStreaming]
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
        const is404 = msg.includes("404");
        if (!is404) {
          opts.addEvent(sessionId, {
            id: `err-${Date.now()}`,
            event: "error_recovery",
            data: { error: `Approval failed: ${msg}` },
            timestamp: Date.now(),
          });
        }
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
      }
    },
    [opts]
  );

  const cancel = useCallback(() => {
    const ss = getSessionState(activeId);
    ss.controller?.abort();
    markStreaming(activeId, false);
  }, [activeId, markStreaming]);

  return { send, approve, reject, cancel, isStreaming };
}
