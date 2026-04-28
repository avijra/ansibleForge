import { Activity, Settings, Terminal, Server } from "lucide-react";
import type { HealthResponse, LLMSettings } from "@/api/types";
import { StatusBadge } from "@/components/common/StatusBadge";

interface HeaderProps {
  health: HealthResponse | null;
  llmSettings: LLMSettings | null;
  onSettingsClick: () => void;
  sessionTitle?: string;
}

export function Header({ health, llmSettings, onSettingsClick, sessionTitle }: HeaderProps) {
  const displayModel = llmSettings?.model || health?.llm_model;
  const isOverride = llmSettings?.source === "runtime";
  const toolCount = health?.tools_available?.length ?? 0;

  return (
    <header className="flex h-11 shrink-0 items-center justify-between border-b border-zinc-800 bg-zinc-950 px-4">
      {/* Left — context breadcrumb */}
      <div className="flex items-center gap-3 min-w-0">
        {sessionTitle && (
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-[10px] text-zinc-600">Session:</span>
            <span className="text-xs font-medium text-zinc-300 truncate max-w-[200px]">
              {sessionTitle}
            </span>
          </div>
        )}
        {!sessionTitle && health && (
          <span className="text-xs text-zinc-500">
            v{health.version}
          </span>
        )}
      </div>

      {/* Right — model + health + settings */}
      <div className="flex items-center gap-3">
        {toolCount > 0 && (
          <div className="hidden lg:flex items-center gap-1 text-[10px] text-zinc-600">
            <Server className="h-3 w-3" />
            <span className="font-mono">{toolCount} tools</span>
          </div>
        )}
        {displayModel && (
          <div className="flex items-center gap-2 text-xs text-zinc-400">
            <Activity className="h-3.5 w-3.5" />
            <span className="hidden md:inline font-mono text-[11px]">
              {displayModel.split("/").pop()}
            </span>
            {isOverride && (
              <span className="rounded bg-teal-500/15 px-1.5 py-0.5 text-[10px] text-teal-400 font-medium">
                override
              </span>
            )}
            {health && <StatusBadge status={health.status} />}
          </div>
        )}
        <button
          onClick={onSettingsClick}
          className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200 transition-colors"
          aria-label="Settings"
        >
          <Settings className="h-4 w-4" />
        </button>
      </div>
    </header>
  );
}
