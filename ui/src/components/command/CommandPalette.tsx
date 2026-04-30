import { Command } from "cmdk";
import {
  FileCode2,
  Play,
  Search,
  Shield,
  Server,
  Brain,
  ScrollText,
  Terminal,
  PanelLeft,
  Settings,
  Cpu,
  Zap,
  GitCompare,
} from "lucide-react";
import type { WorkspaceFile } from "@/api/types";

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceFiles: WorkspaceFile[];
  onOpenFile: (file: WorkspaceFile) => void;
  onAction: (action: string) => void;
}

const ACTIONS = [
  { id: "run-playbook", label: "Run Playbook", icon: Play, shortcut: "" },
  { id: "lint-file", label: "Lint Current File", icon: Shield, shortcut: "" },
  { id: "deploy-host", label: "Deploy to Host", icon: Zap, shortcut: "" },
  { id: "collect-facts", label: "Collect Facts", icon: Search, shortcut: "" },
  { id: "diff-review", label: "Review Changes", icon: GitCompare, shortcut: "" },
];

const NAVIGATION = [
  { id: "nav-logs", label: "Go to Logs", icon: ScrollText, shortcut: "" },
  { id: "nav-hosts", label: "Go to Hosts", icon: Server, shortcut: "" },
  { id: "nav-knowledge", label: "Go to Knowledge Graph", icon: Brain, shortcut: "" },
  { id: "nav-terminal", label: "Toggle Terminal", icon: Terminal, shortcut: "⌘`" },
  { id: "nav-sidebar", label: "Toggle Sidebar", icon: PanelLeft, shortcut: "⌘B" },
];

const SETTINGS = [
  { id: "settings-llm", label: "Configure LLM", icon: Settings, shortcut: "" },
  { id: "settings-model", label: "Switch Model", icon: Cpu, shortcut: "" },
];

export function CommandPalette({
  open,
  onOpenChange,
  workspaceFiles,
  onOpenFile,
  onAction,
}: CommandPaletteProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh]">
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-sm"
        onClick={() => onOpenChange(false)}
      />
      <Command
        className="relative w-full max-w-[520px] rounded-xl border border-zinc-700/50 bg-zinc-900 shadow-2xl shadow-black/50 overflow-hidden"
        onKeyDown={(e) => {
          if (e.key === "Escape") onOpenChange(false);
        }}
      >
        <Command.Input
          placeholder="Search files, actions, settings..."
          className="w-full border-b border-zinc-800 bg-transparent px-4 py-3 text-sm text-zinc-200 placeholder:text-zinc-500 outline-none"
          autoFocus
        />
        <Command.List className="max-h-[320px] overflow-y-auto p-2">
          <Command.Empty className="py-8 text-center text-xs text-zinc-500">
            No results found
          </Command.Empty>

          {workspaceFiles.length > 0 && (
            <Command.Group
              heading={<span className="text-[10px] uppercase tracking-wider text-zinc-600 font-medium px-2">Files</span>}
            >
              {workspaceFiles.map((file) => (
                <Command.Item
                  key={file.path}
                  value={file.path}
                  onSelect={() => {
                    onOpenFile(file);
                    onOpenChange(false);
                  }}
                  className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-zinc-300 cursor-pointer data-[selected=true]:bg-zinc-800 data-[selected=true]:text-zinc-100 transition-colors"
                >
                  <FileCode2 className="h-4 w-4 text-zinc-500 shrink-0" />
                  <span className="truncate flex-1">{file.path}</span>
                  <span className="text-[10px] text-zinc-600 shrink-0 font-mono">
                    {file.size > 1000 ? `${(file.size / 1024).toFixed(1)}k` : `${file.size}b`}
                  </span>
                </Command.Item>
              ))}
            </Command.Group>
          )}

          <Command.Group
            heading={<span className="text-[10px] uppercase tracking-wider text-zinc-600 font-medium px-2">Actions</span>}
          >
            {ACTIONS.map((action) => (
              <Command.Item
                key={action.id}
                value={action.label}
                onSelect={() => {
                  onAction(action.id);
                  onOpenChange(false);
                }}
                className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-zinc-300 cursor-pointer data-[selected=true]:bg-zinc-800 data-[selected=true]:text-zinc-100 transition-colors"
              >
                <action.icon className="h-4 w-4 text-zinc-500 shrink-0" />
                <span className="flex-1">{action.label}</span>
                {action.shortcut && (
                  <kbd className="text-[10px] text-zinc-600 bg-zinc-800 px-1.5 py-0.5 rounded font-mono">{action.shortcut}</kbd>
                )}
              </Command.Item>
            ))}
          </Command.Group>

          <Command.Group
            heading={<span className="text-[10px] uppercase tracking-wider text-zinc-600 font-medium px-2">Navigation</span>}
          >
            {NAVIGATION.map((item) => (
              <Command.Item
                key={item.id}
                value={item.label}
                onSelect={() => {
                  onAction(item.id);
                  onOpenChange(false);
                }}
                className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-zinc-300 cursor-pointer data-[selected=true]:bg-zinc-800 data-[selected=true]:text-zinc-100 transition-colors"
              >
                <item.icon className="h-4 w-4 text-zinc-500 shrink-0" />
                <span className="flex-1">{item.label}</span>
                {item.shortcut && (
                  <kbd className="text-[10px] text-zinc-600 bg-zinc-800 px-1.5 py-0.5 rounded font-mono">{item.shortcut}</kbd>
                )}
              </Command.Item>
            ))}
          </Command.Group>

          <Command.Group
            heading={<span className="text-[10px] uppercase tracking-wider text-zinc-600 font-medium px-2">Settings</span>}
          >
            {SETTINGS.map((item) => (
              <Command.Item
                key={item.id}
                value={item.label}
                onSelect={() => {
                  onAction(item.id);
                  onOpenChange(false);
                }}
                className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-zinc-300 cursor-pointer data-[selected=true]:bg-zinc-800 data-[selected=true]:text-zinc-100 transition-colors"
              >
                <item.icon className="h-4 w-4 text-zinc-500 shrink-0" />
                <span className="flex-1">{item.label}</span>
              </Command.Item>
            ))}
          </Command.Group>
        </Command.List>

        <div className="border-t border-zinc-800 px-4 py-2 flex items-center gap-4 text-[10px] text-zinc-600">
          <span><kbd className="bg-zinc-800 px-1 py-0.5 rounded font-mono">↑↓</kbd> navigate</span>
          <span><kbd className="bg-zinc-800 px-1 py-0.5 rounded font-mono">↵</kbd> select</span>
          <span><kbd className="bg-zinc-800 px-1 py-0.5 rounded font-mono">esc</kbd> close</span>
        </div>
      </Command>
    </div>
  );
}
