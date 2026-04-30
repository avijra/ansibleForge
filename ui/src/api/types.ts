export interface ChatRequest {
  message: string;
  session_id?: string;
  model?: string;
}

export interface ApprovalRequest {
  approved: boolean;
  feedback?: string;
}

export interface ExecuteRequest {
  playbook_content: string;
  inventory_content?: string;
  mode: "check" | "apply";
  extra_vars?: Record<string, unknown>;
}

export interface LintRequest {
  content: string;
  profile?: string;
}

export interface HealthResponse {
  status: string;
  version: string;
  llm_provider: string;
  llm_model: string;
  tools_available: string[];
}

export interface SessionStatusResponse {
  session_id: string;
  status: string;
  step_count: number;
  workspace_path: string;
}

export interface ApprovalResponse {
  session_id: string;
  status: string;
  message: string;
}

export interface ExecuteResponse {
  status: string;
  output: string;
  data: Record<string, unknown>;
}

export interface LintResponse {
  passed: boolean;
  violation_count: number;
  violations: LintViolation[];
  profile: string;
}

export interface LintViolation {
  rule: string;
  severity: string;
  message: string;
  filename: string;
  line: number;
}

export interface CollectionResponse {
  status: string;
  message: string;
  collections: CollectionInfo[];
}

export interface CollectionInfo {
  name: string;
  version: string;
}

export interface PlaybooksResponse {
  session_id: string;
  playbook_count: number;
  playbooks: Record<string, string>;
}

export interface InventoryResponse {
  session_id: string;
  inventory_files: Record<string, string>;
}

export interface WorkspaceFile {
  path: string;
  name: string;
  size: number;
  content: string;
}

export interface WorkspaceFilesResponse {
  session_id: string;
  file_count: number;
  files: WorkspaceFile[];
}

export type AgentEventType =
  | "session_started"
  | "step_start"
  | "thinking"
  | "thinking_delta"
  | "tool_call"
  | "tool_result"
  | "approval_required"
  | "approval_granted"
  | "approval_rejected"
  | "secret_request"
  | "message"
  | "user_message"
  | "progress"
  | "error_recovery"
  | "max_steps"
  | "done";

export interface AgentEvent {
  id: string;
  event: AgentEventType;
  data: Record<string, unknown>;
  timestamp: number;
}

export interface Session {
  id: string;
  status: "active" | "completed" | "awaiting_approval" | "rejected" | "error";
  events: AgentEvent[];
  playbooks: Record<string, string>;
  inventory: Record<string, string>;
  workspaceFiles: WorkspaceFile[];
  createdAt: number;
  title?: string;
}

export interface LLMSettings {
  provider: string;
  model: string;
  api_key_set: boolean;
  api_base: string | null;
  temperature: number;
  max_tokens: number;
  source: "runtime" | "env";
}

export interface LLMSettingsUpdate {
  provider?: string;
  model?: string;
  api_key?: string;
  api_base?: string;
  temperature?: number;
  max_tokens?: number;
}
