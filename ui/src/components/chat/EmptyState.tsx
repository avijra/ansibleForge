import { Terminal, Server, FileCode2, Network, Shield, Play } from "lucide-react";
import { cn } from "@/lib/utils";

interface QuickAction {
  icon: typeof Server;
  label: string;
  description: string;
  prompt: string;
  color: string;
}

const quickActions: QuickAction[] = [
  {
    icon: Play,
    label: "Deploy a service",
    description: "Install and configure on remote hosts",
    prompt: "Deploy ",
    color: "text-teal-400 bg-teal-500/10 ring-teal-500/20",
  },
  {
    icon: Server,
    label: "Check host status",
    description: "Gather facts and verify connectivity",
    prompt: "Check the status of host ",
    color: "text-cyan-400 bg-cyan-500/10 ring-cyan-500/20",
  },
  {
    icon: FileCode2,
    label: "Create a playbook",
    description: "Generate Ansible automation from description",
    prompt: "Create a playbook that ",
    color: "text-blue-400 bg-blue-500/10 ring-blue-500/20",
  },
  {
    icon: Network,
    label: "Manage inventory",
    description: "Set up hosts, groups, and variables",
    prompt: "Set up an inventory for ",
    color: "text-violet-400 bg-violet-500/10 ring-violet-500/20",
  },
  {
    icon: Shield,
    label: "Security hardening",
    description: "Apply security best practices",
    prompt: "Harden the security of ",
    color: "text-amber-400 bg-amber-500/10 ring-amber-500/20",
  },
];

interface EmptyStateProps {
  onAction: (prompt: string) => void;
}

export function EmptyState({ onAction }: EmptyStateProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-8 px-6 py-12">
      {/* Logo */}
      <div className="flex flex-col items-center gap-3">
        <div className="rounded-2xl bg-teal-500/5 p-4 ring-1 ring-teal-500/10">
          <Terminal className="h-10 w-10 text-teal-400/70" />
        </div>
        <div className="text-center">
          <h2 className="text-base font-semibold text-zinc-200">
            Infrastructure Command Center
          </h2>
          <p className="mt-1 text-xs text-zinc-500">
            Describe what you need — AnsibleForge handles the automation
          </p>
        </div>
      </div>

      {/* Quick action cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 w-full max-w-2xl">
        {quickActions.map((action) => (
          <button
            key={action.label}
            onClick={() => onAction(action.prompt)}
            className={cn(
              "group flex items-start gap-3 rounded-lg border border-zinc-800 bg-zinc-900/30 p-3",
              "hover:bg-zinc-900/80 hover:border-zinc-700 transition-all text-left"
            )}
          >
            <div className={cn("rounded-lg p-2 ring-1 shrink-0", action.color)}>
              <action.icon className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <span className="block text-xs font-medium text-zinc-300 group-hover:text-zinc-100 transition-colors">
                {action.label}
              </span>
              <span className="block text-[10px] text-zinc-600 mt-0.5">
                {action.description}
              </span>
            </div>
          </button>
        ))}
      </div>

      {/* Capability hints */}
      <div className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-[10px] text-zinc-700">
        <span>Playbooks</span>
        <span>&middot;</span>
        <span>Roles</span>
        <span>&middot;</span>
        <span>Inventory</span>
        <span>&middot;</span>
        <span>Facts</span>
        <span>&middot;</span>
        <span>Lint</span>
        <span>&middot;</span>
        <span>Galaxy</span>
        <span>&middot;</span>
        <span>Execute</span>
      </div>
    </div>
  );
}
