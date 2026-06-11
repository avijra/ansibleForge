import type {
  AgentEvent,
  AgentEventType,
  ApprovedModel,
  ApprovalResponse,
  CollectionResponse,
  ExecuteRequest,
  ExecuteResponse,
  ExecutionSettings,
  ExecutionSettingsUpdate,
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

export const BACKEND_ORIGIN =
  "__TAURI_INTERNALS__" in window
    ? "http://127.0.0.1:8420"
    : "";

const BASE = `${BACKEND_ORIGIN}/api/v1`;

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
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30_000);
  const signal = options?.signal
    ? AbortSignal.any([options.signal, controller.signal])
    : controller.signal;
  try {
    const res = await fetch(`${BASE}${path}`, {
      headers: authHeaders(),
      ...options,
      signal,
    });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`API ${res.status}: ${body}`);
    }
    return res.json();
  } finally {
    clearTimeout(timeout);
  }
}

export const api = {
  health: (signal?: AbortSignal) => request<HealthResponse>("/health", signal ? { signal } : undefined),
  tools: () => request<{ name: string; description: string }[]>("/tools"),

  sessionStatus: (id: string) =>
    request<SessionStatusResponse>(`/chat/${id}/status`),

  cancelSession: (id: string) =>
    request<{ session_id: string; status: string }>(`/chat/${id}/cancel`, {
      method: "POST",
    }),

  approve: (id: string, responseData?: Record<string, unknown>) =>
    request<ApprovalResponse>(`/chat/${id}/approve`, {
      method: "POST",
      body: JSON.stringify(responseData ? { response_data: responseData } : {}),
    }),

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
    models: () => request<ApprovedModel[]>("/settings/llm/models"),
    update: (body: LLMSettingsUpdate) =>
      request<LLMSettings>("/settings/llm", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    reset: () =>
      request<LLMSettings>("/settings/llm", { method: "DELETE" }),
    test: (body: LLMSettingsUpdate) =>
      request<{ ok: boolean; error?: string; reply?: string; model?: string }>(
        "/settings/llm/test",
        { method: "POST", body: JSON.stringify(body) },
      ),
  },

  executionSettings: {
    get: () => request<ExecutionSettings>("/settings/execution"),
    update: (body: ExecutionSettingsUpdate) =>
      request<ExecutionSettings>("/settings/execution", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    reset: () =>
      request<ExecutionSettings>("/settings/execution", { method: "DELETE" }),
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

const sessionLastSeq = new Map<string, number>();
const SEQ_STORAGE_KEY = "ansibleforge_last_seq";

function _loadPersistedSeqs(): void {
  try {
    const raw = localStorage.getItem(SEQ_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Record<string, number>;
      for (const [k, v] of Object.entries(parsed)) {
        sessionLastSeq.set(k, v);
      }
    }
  } catch { /* ignore corrupt data */ }
}

function _persistSeqs(): void {
  try {
    const obj: Record<string, number> = {};
    for (const [k, v] of sessionLastSeq) obj[k] = v;
    localStorage.setItem(SEQ_STORAGE_KEY, JSON.stringify(obj));
  } catch { /* storage full or unavailable */ }
}

_loadPersistedSeqs();

export function getLastSeq(sessionId: string): number {
  return sessionLastSeq.get(sessionId) ?? 0;
}

function setLastSeq(sessionId: string, seq: number): void {
  sessionLastSeq.set(sessionId, seq);
  _persistSeqs();
}

export function clearLastSeq(sessionId: string): void {
  sessionLastSeq.delete(sessionId);
  _persistSeqs();
}

export function reconnectStream(
  sessionId: string,
  fromSeq: number,
  onEvent: (event: AgentEvent) => void,
  onDone: (status: string) => void,
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
      let doneStatus = "completed";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("id: ")) {
            const seq = parseInt(line.slice(4).trim(), 10);
            if (!isNaN(seq)) setLastSeq(sessionId, seq);
          } else if (line.startsWith("event: ")) {
            currentEvent = line.slice(7).trim() as AgentEventType;
          } else if (line.startsWith("data: ") && currentEvent) {
            try {
              const data = JSON.parse(line.slice(6));
              if (currentEvent === "done") {
                receivedDone = true;
                doneStatus = (data.status as string) || "completed";
                onDone(doneStatus);
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
      if (!receivedDone) onDropped();
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
  onDone: (sessionId: string, status: string) => void,
  onDropped: (sessionId: string) => void,
  projectPath?: string,
): AbortController {
  const controller = new AbortController();

  if (sessionId) clearLastSeq(sessionId);

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
      let doneStatus = "completed";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("id: ")) {
            const seq = parseInt(line.slice(4).trim(), 10);
            if (!isNaN(seq) && lastSessionId) setLastSeq(lastSessionId, seq);
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
                doneStatus = (data.status as string) || "completed";
                onDone(data.session_id, doneStatus);
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

      if (!receivedDone) {
        if (lastSessionId) {
          onDropped(lastSessionId);
        } else {
          onError(new Error("Connection lost before session was established. Please try again."));
        }
      }
    })
    .catch((err) => {
      if (err.name !== "AbortError") {
        onError(err);
      }
    });

  return controller;
}
