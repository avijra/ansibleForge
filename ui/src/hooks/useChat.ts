import { useCallback, useRef, useState } from "react";
import { streamChat, api } from "@/api/client";
import type { AgentEvent, Session } from "@/api/types";

interface UseChatOptions {
  addEvent: (sessionId: string, event: AgentEvent) => void;
  updateStatus: (sessionId: string, status: Session["status"]) => void;
  updateSessionId: (oldId: string, newId: string) => void;
  setPlaybooks: (sessionId: string, playbooks: Record<string, string>) => void;
  setInventory: (sessionId: string, inventory: Record<string, string>) => void;
}

export function useChat(opts: UseChatOptions) {
  const [isStreaming, setIsStreaming] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);
  const serverSessionRef = useRef<string | null>(null);

  const send = useCallback(
    (message: string, sessionId: string) => {
      if (isStreaming) return;
      setIsStreaming(true);

      const serverSid = serverSessionRef.current;

      opts.addEvent(sessionId, {
        id: `usr-${Date.now()}`,
        event: "user_message",
        data: { content: message },
        timestamp: Date.now(),
      });

      const controller = streamChat(
        message,
        serverSid,
        (event) => {
          if (
            event.event === "session_started" &&
            event.data?.session_id
          ) {
            serverSessionRef.current = event.data.session_id as string;
            return;
          }

          opts.addEvent(sessionId, event);

          if (event.event === "approval_required") {
            opts.updateStatus(sessionId, "awaiting_approval");
          }
          if (event.event === "secret_request") {
            opts.updateStatus(sessionId, "awaiting_approval");
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
          setIsStreaming(false);
        },
        async (returnedSessionId) => {
          serverSessionRef.current = returnedSessionId;
          opts.updateSessionId(sessionId, returnedSessionId);

          try {
            const pb = await api.playbooks(returnedSessionId);
            opts.setPlaybooks(returnedSessionId, pb.playbooks);
          } catch { /* session may have been cleaned up */ }

          try {
            const inv = await api.inventory(returnedSessionId);
            opts.setInventory(returnedSessionId, inv.inventory_files);
          } catch { /* ignore */ }

          setIsStreaming(false);
        }
      );

      controllerRef.current = controller;
    },
    [isStreaming, opts]
  );

  const approve = useCallback(
    async (sessionId: string) => {
      const sid = serverSessionRef.current || sessionId;
      try {
        await api.approve(sid);
        opts.updateStatus(sessionId, "active");
      } catch (err) {
        opts.addEvent(sessionId, {
          id: `err-${Date.now()}`,
          event: "error_recovery",
          data: { error: `Approval failed: ${err}` },
          timestamp: Date.now(),
        });
      }
    },
    [opts]
  );

  const reject = useCallback(
    async (sessionId: string, feedback = "") => {
      const sid = serverSessionRef.current || sessionId;
      try {
        await api.reject(sid, feedback);
        opts.updateStatus(sessionId, "rejected");
      } catch (err) {
        opts.addEvent(sessionId, {
          id: `err-${Date.now()}`,
          event: "error_recovery",
          data: { error: `Rejection failed: ${err}` },
          timestamp: Date.now(),
        });
      }
    },
    [opts]
  );

  const cancel = useCallback(() => {
    controllerRef.current?.abort();
    setIsStreaming(false);
  }, []);

  return { send, approve, reject, cancel, isStreaming };
}
