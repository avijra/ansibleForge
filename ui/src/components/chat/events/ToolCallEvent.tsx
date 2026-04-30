import { Wrench } from "lucide-react";
import type { AgentEvent } from "@/api/types";
import { JsonBlock } from "@/components/common/JsonBlock";

const toolLabels: Record<string, string> = {
  generate_playbook: "Playbook Generator",
  scaffold_role: "Role Scaffolder",
  manage_inventory: "Inventory Manager",
  manage_vault: "Vault Manager",
  run_lint: "Lint Runner",
  run_molecule: "Molecule Tests",
  manage_galaxy: "Galaxy Manager",
  execute_playbook: "Executor",
  collect_facts: "Facts Collector",
  search_docs: "Doc Search",
  web_search: "Web Search",
  write_file: "File Writer",
  request_secret: "Secret Request",
};

export function ToolCallEvent({ event }: { event: AgentEvent }) {
  const tool = (event.data.tool as string) || "unknown";
  const args = event.data.arguments as Record<string, unknown> | undefined;

  return (
    <div className="animate-slide-in rounded-lg border border-blue-800/25 bg-blue-950/15 shadow-[0_0_12px_-4px_rgba(59,130,246,0.10)] p-3 space-y-2">
      <div className="flex items-center gap-2">
        <Wrench className="h-3.5 w-3.5 text-zinc-400" />
        <span className="text-xs font-medium text-zinc-300">
          {toolLabels[tool] || tool}
        </span>
        <span className="ml-auto font-mono text-[10px] text-zinc-600">
          {tool}
        </span>
      </div>
      {args && Object.keys(args).length > 0 && (
        <JsonBlock data={args} maxLines={8} />
      )}
    </div>
  );
}
