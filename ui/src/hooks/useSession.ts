import { useCallback, useEffect, useState } from "react";
import type { AgentEvent, Session, WorkspaceFile } from "@/api/types";
import { loadActiveId, loadSessions, saveActiveId, saveSessions } from "@/lib/sessionStorage";

function findLastIndex<T>(arr: T[], predicate: (item: T) => boolean): number {
  for (let i = arr.length - 1; i >= 0; i--) {
    if (predicate(arr[i])) return i;
  }
  return -1;
}

let sessionCounter = 0;

function createSession(): Session {
  return {
    id: `local-${++sessionCounter}`,
    status: "active",
    events: [],
    playbooks: {},
    inventory: {},
    workspaceFiles: [],
    createdAt: Date.now(),
    title: undefined,
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
    const restored = loadSessions();
    return restored.length > 0 ? restored : [createSession()];
  });
  const [activeId, setActiveId] = useState<string>(() => {
    const restored = loadActiveId();
    return restored && sessions.some((s) => s.id === restored) ? restored : sessions[0].id;
  });

  useEffect(() => { saveSessions(sessions); }, [sessions]);
  useEffect(() => { saveActiveId(activeId); }, [activeId]);

  const active = sessions.find((s) => s.id === activeId) ?? sessions[0];

  const newSession = useCallback(() => {
    const s = createSession();
    setSessions((prev) => [...prev, s]);
    setActiveId(s.id);
    return s;
  }, []);

  const deleteSession = useCallback(
    (sessionId: string) => {
      setSessions((prev) => {
        const filtered = prev.filter((s) => s.id !== sessionId);
        if (filtered.length === 0) {
          const fresh = createSession();
          return [fresh];
        }
        return filtered;
      });
      if (activeId === sessionId) {
        setSessions((prev) => {
          setActiveId(prev[0]?.id ?? "");
          return prev;
        });
      }
    },
    [activeId]
  );

  const clearAllSessions = useCallback(() => {
    const fresh = createSession();
    setSessions([fresh]);
    setActiveId(fresh.id);
  }, []);

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

  return {
    sessions,
    active,
    activeId,
    setActiveId,
    newSession,
    deleteSession,
    clearAllSessions,
    addEvent,
    updateStatus,
    updateSessionId,
    setPlaybooks,
    setInventory,
    setWorkspaceFiles,
  };
}
