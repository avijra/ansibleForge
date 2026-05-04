import { useCallback, useEffect, useState } from "react";
import type { AgentEvent, Session, WorkspaceFile } from "@/api/types";
import { api } from "@/api/client";
import { loadSessions, saveSessions } from "@/lib/sessionStorage";

function findLastIndex<T>(arr: T[], predicate: (item: T) => boolean): number {
  for (let i = arr.length - 1; i >= 0; i--) {
    if (predicate(arr[i])) return i;
  }
  return -1;
}

let sessionCounter = 0;

function createSession(projectPath: string): Session {
  return {
    id: `local-${++sessionCounter}`,
    status: "active",
    events: [],
    playbooks: {},
    inventory: {},
    workspaceFiles: [],
    createdAt: Date.now(),
    title: undefined,
    projectPath,
  };
}

function deriveTitle(events: AgentEvent[]): string | undefined {
  const first = events.find((e) => e.event === "user_message");
  if (!first) return undefined;
  const content = (first.data.content as string) || "";
  const trimmed = content.trim();
  if (!trimmed) return undefined;
  return trimmed.length > 50 ? trimmed.slice(0, 47) + "..." : trimmed;
}

export function useSession() {
  const [sessions, setSessions] = useState<Session[]>(() => {
    return loadSessions();
  });
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => { saveSessions(sessions); }, [sessions]);

  const active = activeId ? sessions.find((s) => s.id === activeId) : undefined;

  const newSession = useCallback((projectPath: string) => {
    const s = createSession(projectPath);
    setSessions((prev) => [...prev, s]);
    setActiveId(s.id);
    return s;
  }, []);

  const restoreRemoteSession = useCallback(
    (sessionId: string, projectPath: string, title?: string) => {
      setSessions((prev) => {
        const existing = prev.find((s) => s.id === sessionId);
        if (existing) return prev;
        return [
          ...prev,
          {
            id: sessionId,
            status: "active" as const,
            events: [],
            playbooks: {},
            inventory: {},
            workspaceFiles: [],
            createdAt: Date.now(),
            title,
            projectPath,
          },
        ];
      });
      setActiveId(sessionId);
    },
    []
  );

  const deleteSession = useCallback(
    (sessionId: string) => {
      api.sessions.delete(sessionId).catch(() => {});
      setSessions((prev) => {
        const filtered = prev.filter((s) => s.id !== sessionId);
        if (sessionId === activeId) {
          setActiveId(filtered.length > 0 ? filtered[0].id : null);
        }
        return filtered;
      });
    },
    [activeId]
  );

  const clearAllSessions = useCallback(() => {
    setSessions((prev) => {
      for (const s of prev) {
        api.sessions.delete(s.id).catch(() => {});
      }
      return [];
    });
    setActiveId(null);
  }, []);

  const resetSession = useCallback(
    async (sessionId: string) => {
      if (!sessionId.startsWith("local-")) {
        await api.sessions.reset(sessionId);
      }
      setSessions((prev) =>
        prev.map((s) =>
          s.id === sessionId
            ? { ...s, events: [], status: "active" as const, title: undefined }
            : s
        )
      );
    },
    []
  );

  const addEvent = useCallback(
    (sessionId: string, event: AgentEvent) => {
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id !== sessionId) return s;

          if (event.event === "thinking_delta") {
            const events = [...s.events];
            const lastIdx = findLastIndex(events, (e) => e.event === "thinking");
            if (lastIdx >= 0) {
              const existing = events[lastIdx];
              events[lastIdx] = {
                ...existing,
                data: {
                  ...existing.data,
                  content:
                    ((existing.data.content as string) || "") +
                    ((event.data.content as string) || ""),
                },
              };
              return { ...s, events };
            }
            return {
              ...s,
              events: [
                ...s.events,
                { ...event, event: "thinking" as const },
              ],
            };
          }

          if (event.event === "message_delta") {
            const events = [...s.events];
            const lastIdx = findLastIndex(
              events,
              (e) => e.event === "message" && e.data._streaming === true
            );
            if (lastIdx >= 0) {
              const existing = events[lastIdx];
              events[lastIdx] = {
                ...existing,
                data: {
                  ...existing.data,
                  content:
                    ((existing.data.content as string) || "") +
                    ((event.data.content as string) || ""),
                },
              };
              return { ...s, events };
            }
            return {
              ...s,
              events: [
                ...s.events,
                {
                  ...event,
                  event: "message" as const,
                  data: { content: (event.data.content as string) || "", _streaming: true },
                },
              ],
            };
          }

          if (event.event === "message") {
            const events = [...s.events];
            const streamIdx = findLastIndex(
              events,
              (e) => e.event === "message" && e.data._streaming === true
            );
            if (streamIdx >= 0) {
              events[streamIdx] = {
                ...events[streamIdx],
                data: {
                  content: (event.data.content as string) || (events[streamIdx].data.content as string) || "",
                  usage: event.data.usage,
                },
              };
              const title = s.title || deriveTitle(events);
              return { ...s, events, title };
            }
          }

          if (event.event === "live_log") {
            const events = [...s.events];
            const liveCount = events.filter((e) => e.event === "live_log").length;
            if (liveCount >= 200) {
              const firstLiveIdx = events.findIndex((e) => e.event === "live_log");
              if (firstLiveIdx >= 0) events.splice(firstLiveIdx, 1);
            }
            return { ...s, events: [...events, event] };
          }

          if (event.event === "progress") {
            const events = [...s.events];
            const lastIdx = findLastIndex(events, (e) => e.event === "progress");
            if (lastIdx >= 0 && lastIdx === events.length - 1) {
              events[lastIdx] = { ...event };
              return { ...s, events };
            }
          }

          const newEvents = [...s.events, event];
          const title = s.title || deriveTitle(newEvents);
          return { ...s, events: newEvents, title };
        })
      );
    },
    []
  );

  const updateStatus = useCallback(
    (sessionId: string, status: Session["status"]) => {
      setSessions((prev) =>
        prev.map((s) => (s.id === sessionId ? { ...s, status } : s))
      );
    },
    []
  );

  const updateSessionId = useCallback(
    (oldId: string, newId: string) => {
      setSessions((prev) =>
        prev.map((s) => (s.id === oldId ? { ...s, id: newId } : s))
      );
      if (activeId === oldId) setActiveId(newId);
    },
    [activeId]
  );

  const setPlaybooks = useCallback(
    (sessionId: string, playbooks: Record<string, string>) => {
      setSessions((prev) =>
        prev.map((s) => (s.id === sessionId ? { ...s, playbooks } : s))
      );
    },
    []
  );

  const setInventory = useCallback(
    (sessionId: string, inventory: Record<string, string>) => {
      setSessions((prev) =>
        prev.map((s) => (s.id === sessionId ? { ...s, inventory } : s))
      );
    },
    []
  );

  const setWorkspaceFiles = useCallback(
    (sessionId: string, workspaceFiles: WorkspaceFile[]) => {
      setSessions((prev) =>
        prev.map((s) => (s.id === sessionId ? { ...s, workspaceFiles } : s))
      );
    },
    []
  );

  const setEvents = useCallback(
    (sessionId: string, events: AgentEvent[]) => {
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id !== sessionId) return s;
          const title = s.title || deriveTitle(events);
          return { ...s, events, title };
        })
      );
    },
    []
  );

  return {
    sessions,
    active,
    activeId,
    setActiveId,
    newSession,
    restoreRemoteSession,
    deleteSession,
    clearAllSessions,
    resetSession,
    addEvent,
    setEvents,
    updateStatus,
    updateSessionId,
    setPlaybooks,
    setInventory,
    setWorkspaceFiles,
  };
}
