import { useMemo } from "react";
import type { AgentEvent, WorkspaceFile } from "@/api/types";

export interface Suggestion {
  type: "host" | "module" | "role" | "playbook" | "command" | "file";
  label: string;
  detail?: string;
}

function extractHostsFromEvents(events: AgentEvent[]): string[] {
  const hosts = new Set<string>();
  for (const evt of events) {
    if (evt.event !== "tool_result") continue;
    const data = (evt.data.data as Record<string, unknown>) ?? evt.data;

    const facts = data.facts as Record<string, unknown> | undefined;
    if (facts) {
      for (const host of Object.keys(facts)) {
        hosts.add(host);
      }
    }

    const evtEvents = data.events as Array<Record<string, unknown>> | undefined;
    if (evtEvents) {
      for (const e of evtEvents) {
        const host = e.host as string | undefined;
        if (host) hosts.add(host);
      }
    }
  }
  return Array.from(hosts);
}

function extractFromWorkspaceFiles(files: WorkspaceFile[]): {
  roles: string[];
  playbooks: string[];
  modules: string[];
} {
  const roles = new Set<string>();
  const playbooks = new Set<string>();
  const modules = new Set<string>();

  for (const file of files) {
    if (file.path.includes("/roles/") && file.path.includes("/tasks/")) {
      const parts = file.path.split("/");
      const rolesIdx = parts.indexOf("roles");
      if (rolesIdx >= 0 && rolesIdx + 1 < parts.length) {
        roles.add(parts[rolesIdx + 1]);
      }
    }

    if (
      (file.name.endsWith(".yml") || file.name.endsWith(".yaml")) &&
      !file.path.includes("/roles/") &&
      !file.path.includes("/vars/") &&
      !file.path.includes("/defaults/") &&
      !file.path.includes("/handlers/")
    ) {
      playbooks.add(file.name);
    }

    const moduleRegex = /^\s*-?\s*(?:ansible\.builtin\.\w+|\w+\.\w+\.\w+):/gm;
    let match: RegExpExecArray | null;
    while ((match = moduleRegex.exec(file.content)) !== null) {
      const mod = match[0].replace(/^[\s-]*/, "").replace(/:$/, "").trim();
      if (mod) modules.add(mod);
    }
  }

  return {
    roles: Array.from(roles),
    playbooks: Array.from(playbooks),
    modules: Array.from(modules),
  };
}

const SLASH_COMMANDS: Suggestion[] = [
  { type: "command", label: "/deploy", detail: "Deploy a playbook to hosts" },
  { type: "command", label: "/lint", detail: "Run ansible-lint on workspace" },
  { type: "command", label: "/facts", detail: "Collect facts from hosts" },
  { type: "command", label: "/inventory", detail: "Show or modify inventory" },
  { type: "command", label: "/vault", detail: "Encrypt/decrypt with ansible-vault" },
  { type: "command", label: "/check", detail: "Dry-run a playbook" },
];

export function useAnsibleContext(
  events: AgentEvent[],
  workspaceFiles: WorkspaceFile[]
): {
  suggestions: Suggestion[];
  getFiltered: (prefix: string, trigger: "@" | "/") => Suggestion[];
} {
  const suggestions = useMemo(() => {
    const result: Suggestion[] = [];

    const hosts = extractHostsFromEvents(events);
    for (const h of hosts) {
      result.push({ type: "host", label: h, detail: "Host" });
    }

    const { roles, playbooks, modules } = extractFromWorkspaceFiles(workspaceFiles);

    for (const r of roles) {
      result.push({ type: "role", label: r, detail: "Role" });
    }
    for (const p of playbooks) {
      result.push({ type: "playbook", label: p, detail: "Playbook" });
    }
    for (const m of modules.slice(0, 50)) {
      result.push({ type: "module", label: m, detail: "Module" });
    }

    const addedPaths = new Set(playbooks);
    for (const f of workspaceFiles) {
      if (addedPaths.has(f.name) || addedPaths.has(f.path)) continue;
      addedPaths.add(f.path);
      result.push({ type: "file", label: f.path, detail: `${(f.size / 1024).toFixed(1)}KB` });
    }

    return result;
  }, [events, workspaceFiles]);

  const getFiltered = useMemo(
    () => (prefix: string, trigger: "@" | "/") => {
      if (trigger === "/") {
        const q = prefix.toLowerCase();
        return SLASH_COMMANDS.filter((s) => s.label.toLowerCase().includes(q));
      }

      const q = prefix.toLowerCase();
      return suggestions.filter((s) => s.label.toLowerCase().includes(q));
    },
    [suggestions]
  );

  return { suggestions, getFiltered };
}
