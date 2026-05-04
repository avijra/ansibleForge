import type {
  AgentEvent,
  AgentEventType,
  ApprovalResponse,
  CollectionResponse,
  ExecuteRequest,
  ExecuteResponse,
  HealthResponse,
  InventoryResponse,
  LintRequest,
  LintResponse,
  LLMSettings,
  LLMSettingsUpdate,
  PlaybooksResponse,
  SessionListItem,
  SessionStatusResponse,
  WorkspaceFilesResponse,
} from "./types";

const BASE = "/api/v1";

export function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const key = import.meta.env.VITE_API_KEY;
  if (key) {
    headers["X-API-Key"] = key;
  }
  return headers;
}

export async function request<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: authHeaders(),
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json();
}

export const api = {
  health: () => request<HealthResponse>("/health"),
  tools: () => request<{ name: string; description: string }[]>("/tools"),

  sessionStatus: (id: string) =>
    request<SessionStatusResponse>(`/chat/${id}/status`),

  approve: (id: string) =>
    request<ApprovalResponse>(`/chat/${id}/approve`, { method: "POST" }),

  reject: (id: string, feedback = "") =>
    request<ApprovalResponse>(`/chat/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ approved: false, feedback }),
    }),

  execute: (req: ExecuteRequest) =>
    request<ExecuteResponse>("/execute", {
      method: "POST",
      body: JSON.stringify(req),
    }),

  lint: (req: LintRequest) =>
    request<LintResponse>("/lint", {
      method: "POST",
      body: JSON.stringify(req),
    }),

  playbooks: (sessionId: string) =>
    request<PlaybooksResponse>(`/playbooks/${sessionId}`),

  inventory: (sessionId: string) =>
    request<InventoryResponse>(`/inventory/${sessionId}`),

  workspaceFiles: (sessionId: string) =>
    request<WorkspaceFilesResponse>(`/workspace/${sessionId}/files`),

  saveFile: (sessionId: string, path: string, content: string) =>
    request<{ path: string; size: number; ok: boolean }>(`/workspace/${sessionId}/files`, {
      method: "PUT",
      body: JSON.stringify({ path, content }),
    }),

  collections: {
    list: () => request<CollectionResponse>("/collections"),
    search: (q: string) =>
      request<CollectionResponse>(`/collections/search?query=${encodeURIComponent(q)}`),
    install: (name: string, version?: string) =>
      request<CollectionResponse>("/collections/install", {
        method: "POST",
        body: JSON.stringify({ name, version }),
      }),
  },

  llmSettings: {
    get: () => request<LLMSettings>("/settings/llm"),
    update: (body: LLMSettingsUpdate) =>
      request<LLMSettings>("/settings/llm", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    reset: () =>
      request<LLMSettings>("/settings/llm", { method: "DELETE" }),
  },

  sessions: {
    list: (projectPath?: string) => {
      const qs = projectPath
        ? `?project_path=${encodeURIComponent(projectPath)}`
        : "";
      return request<{ sessions: SessionListItem[] }>(`/sessions${qs}`);
    },
    reset: (sessionId: string) =>
      request<{ session_id: string; status: string }>(`/sessions/${sessionId}/reset`, {
        method: "POST",
      }),
    delete: (sessionId: string) =>
      request<{ session_id: string; deleted: boolean }>(`/sessions/${sessionId}`, {
        method: "DELETE",
      }),
  },

  rules: {
    get: (sessionId: string) =>
      request<{ session_id: string; content: string; exists: boolean; path: string }>(
        `/rules/${sessionId}`
      ),
    update: (sessionId: string, content: string) =>
      request<{ session_id: string; status: string }>(
        `/rules/${sessionId}`,
        { method: "PUT", body: JSON.stringify({ content }) }
      ),
  },

  checkpoints: {
    list: (sessionId: string) =>
      request<{ session_id: string; checkpoints: { hash: string; short_hash: string; label: string; timestamp: number }[] }>(
        `/checkpoints/${sessionId}`
      ),
    revert: (sessionId: string, hash: string) =>
      request<{ session_id: string; success: boolean; reverted_to: string; files_changed: number }>(
        `/checkpoints/${sessionId}/revert`,
        { method: "POST", body: JSON.stringify({ hash }) }
      ),
  },

  secrets: {
    submit: (sessionId: string, name: string, value: string, description = "") =>
      request<{ session_id: string; name: string; status: string; message: string }>(
        `/chat/${sessionId}/secrets`,
        {
          method: "POST",
          body: JSON.stringify({ name, value, description }),
        }
      ),
    list: (sessionId: string) =>
      request<{ session_id: string; secrets: { name: string; description: string }[] }>(
        `/chat/${sessionId}/secrets`
      ),
    delete: (sessionId: string, name: string) =>
      request<{ session_id: string; name: string; status: string; message: string }>(
        `/chat/${sessionId}/secrets/${name}`,
        { method: "DELETE" }
      ),
    cancel: (sessionId: string) =>
      request<{ session_id: string; name: string; status: string; message: string }>(
        `/chat/${sessionId}/secrets/cancel`,
        { method: "POST" }
      ),
  },
};

let eventCounter = 0;

export let lastSeq = 0;

export function reconnectStream(
  sessionId: string,
  fromSeq: number,
  onEvent: (event: AgentEvent) => void,
  onDone: () => void,
  onDropped: () => void,
): AbortController {
  const controller = new AbortController();

  fetch(`${BASE}/chat/${sessionId}/stream?from_seq=${fromSeq}`, {
    headers: authHeaders(),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        onDropped();
        return;
      }
      const reader = res.body?.getReader();
      if (!reader) { onDropped(); return; }

      const decoder = new TextDecoder();
      let buffer = "";
      let currentEvent: AgentEventType | null = null;
      let receivedDone = false;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("id: ")) {
            const seq = parseInt(line.slice(4).trim(), 10);
            if (!isNaN(seq)) lastSeq = seq;
          } else if (line.startsWith("event: ")) {
            currentEvent = line.slice(7).trim() as AgentEventType;
          } else if (line.startsWith("data: ") && currentEvent) {
            try {
              const data = JSON.parse(line.slice(6));
              if (currentEvent === "done") {
                receivedDone = true;
                onDone();
              } else {
                onEvent({
                  id: `evt-${++eventCounter}`,
                  event: currentEvent,
                  data,
                  timestamp: Date.now(),
                });
              }
            } catch { /* skip */ }
            currentEvent = null;
          }
        }
      }
      if (!receivedDone) onDropped(); else onDone();
    })
    .catch((err) => {
      if (err.name !== "AbortError") onDropped();
    });

  return controller;
}

export function streamChat(
  message: string,
  sessionId: string | null,
  onEvent: (event: AgentEvent) => void,
  onError: (error: Error) => void,
  onDone: (sessionId: string) => void,
  onDropped: (sessionId: string) => void,
  projectPath?: string,
): AbortController {
  const controller = new AbortController();

  lastSeq = 0;

  fetch(`${BASE}/chat`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({
      message,
      session_id: sessionId,
      project_path: projectPath || undefined,
    }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const body = await res.json();
          detail = body.detail || body.message || detail;
        } catch {
          /* no parseable body */
        }
        const friendly: Record<number, string> = {
          401: "Authentication failed — check your API key in Settings.",
          403: "Access denied — your API key may lack permissions.",
          422: `Invalid request: ${detail}`,
          500: `Server error: ${detail}`,
          502: "LLM provider unreachable — check your provider/model settings.",
          503: "Service temporarily unavailable — try again shortly.",
        };
        throw new Error(friendly[res.status] || `Unexpected error (${detail})`);
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";
      let currentEvent: AgentEventType | null = null;

      let receivedDone = false;
      let lastSessionId: string | null = sessionId;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("id: ")) {
            const seq = parseInt(line.slice(4).trim(), 10);
            if (!isNaN(seq)) lastSeq = seq;
          } else if (line.startsWith("event: ")) {
            currentEvent = line.slice(7).trim() as AgentEventType;
          } else if (line.startsWith("data: ") && currentEvent) {
            try {
              const data = JSON.parse(line.slice(6));

              if (currentEvent === "session_started" && data.session_id) {
                lastSessionId = data.session_id;
              }

              if (currentEvent === "done") {
                receivedDone = true;
                onDone(data.session_id);
              } else {
                onEvent({
                  id: `evt-${++eventCounter}`,
                  event: currentEvent,
                  data,
                  timestamp: Date.now(),
                });
              }
            } catch {
              // skip malformed JSON
            }
            currentEvent = null;
          } else if (line.trim() === "") {
            currentEvent = null;
          }
        }
      }

      if (!receivedDone && lastSessionId) {
        onDropped(lastSessionId);
      }
    })
    .catch((err) => {
      if (err.name !== "AbortError") {
        onError(err);
      }
    });

  return controller;
}
