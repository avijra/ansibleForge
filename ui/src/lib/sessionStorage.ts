import type { Session } from "@/api/types";

const SESSIONS_KEY = "ansibleforge_sessions";
const ACTIVE_KEY = "ansibleforge_active_id";
const MAX_SESSIONS = 30;

interface StoredSession {
  id: string;
  status: Session["status"];
  events: Session["events"];
  playbooks: Record<string, string>;
  inventory: Record<string, string>;
  createdAt: number;
  title?: string;
}

function stripLargeData(session: Session): StoredSession {
  return {
    id: session.id,
    status: session.status,
    events: session.events.filter((e) => e.event !== "progress").slice(-200),
    playbooks: session.playbooks,
    inventory: session.inventory,
    createdAt: session.createdAt,
    title: session.title,
  };
}

function restoreSession(stored: StoredSession): Session {
  return {
    ...stored,
    workspaceFiles: [],
  };
}

let saveTimer: ReturnType<typeof setTimeout> | null = null;

export function saveSessions(sessions: Session[]): void {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    try {
      const trimmed = sessions
        .sort((a, b) => b.createdAt - a.createdAt)
        .slice(0, MAX_SESSIONS)
        .map(stripLargeData);
      localStorage.setItem(SESSIONS_KEY, JSON.stringify(trimmed));
    } catch {
      // quota exceeded or unavailable
    }
  }, 500);
}

export function loadSessions(): Session[] {
  try {
    const raw = localStorage.getItem(SESSIONS_KEY);
    if (!raw) return [];
    const parsed: StoredSession[] = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.map(restoreSession);
  } catch {
    return [];
  }
}

export function saveActiveId(id: string): void {
  try {
    localStorage.setItem(ACTIVE_KEY, id);
  } catch {
    // ignore
  }
}

export function loadActiveId(): string | null {
  try {
    return localStorage.getItem(ACTIVE_KEY);
  } catch {
    return null;
  }
}
