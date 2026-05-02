import { useEffect, useRef, useState } from "react";
import { Activity, Settings, Server, X } from "lucide-react";
import type { HealthResponse, LLMSettings } from "@/api/types";
import { api } from "@/api/client";
import { StatusBadge } from "@/components/common/StatusBadge";

interface HeaderProps {
  health: HealthResponse | null;
  llmSettings: LLMSettings | null;
  onSettingsClick: () => void;
  sessionTitle?: string;
}

interface ToolSummary {
  name: string;
  description: string;
}

export function Header({ health, llmSettings, onSettingsClick, sessionTitle }: HeaderProps) {
  const displayModel = llmSettings?.model || health?.llm_model;
  const isOverride = llmSettings?.source === "runtime";
  const toolCount = health?.tools_available?.length ?? 0;

  const [showTools, setShowTools] = useState(false);
  const [tools, setTools] = useState<ToolSummary[]>([]);
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!showTools || tools.length > 0) return;
    api.tools().then(setTools).catch(() => {});
  }, [showTools, tools.length]);

  useEffect(() => {
    if (!showTools) return;
    function handleClick(e: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setShowTools(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [showTools]);

  return (
    <header
      className="flex h-11 shrink-0 items-center justify-between border-b border-zinc-800 bg-zinc-950 px-4"
      style={{ WebkitAppRegion: "drag" } as React.CSSProperties}
    >
      <div className="flex items-center gap-3 min-w-0 pl-16">
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

      <div className="flex items-center gap-3" style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}>
        {toolCount > 0 && (
          <div className="relative">
            <button
              onClick={() => setShowTools((v) => !v)}
              className="hidden lg:flex items-center gap-1 text-[10px] text-sky-500/70 hover:text-sky-400 transition-colors"
            >
              <Server className="h-3 w-3" />
              <span className="font-mono">{toolCount} tools</span>
            </button>

            {showTools && (
              <div
                ref={popoverRef}
                className="absolute right-0 top-full mt-2 w-80 max-h-96 overflow-y-auto rounded-lg border border-zinc-700/50 bg-zinc-900 shadow-xl z-50"
              >
                <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-800">
                  <span className="text-xs font-medium text-zinc-300">
                    Agent Tools ({toolCount})
                  </span>
                  <button
                    onClick={() => setShowTools(false)}
                    className="text-zinc-500 hover:text-zinc-300 transition-colors"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
                <div className="p-1.5">
                  {tools.map((t) => (
                    <div key={t.name} className="px-2.5 py-2 rounded-md hover:bg-zinc-800/60 transition-colors">
                      <div className="font-mono text-[11px] text-sky-400/90">{t.name}</div>
                      <div className="text-[10px] text-zinc-500 mt-0.5 leading-relaxed">{t.description}</div>
                    </div>
                  ))}
                  {tools.length === 0 && (
                    <div className="px-2.5 py-3 text-[11px] text-zinc-600 text-center">Loading…</div>
                  )}
                </div>
                {health?.external_tools && (
                  <div className="border-t border-zinc-800">
                    <div className="px-3 py-1.5">
                      <span className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider">
                        Runtime Dependencies
                      </span>
                    </div>
                    <div className="px-1.5 pb-1.5">
                      {Object.entries(health.external_tools).map(([name, path]) => {
                        const installed = !path.includes("not ");
                        return (
                          <div key={name} className="flex items-center justify-between px-2.5 py-1.5">
                            <span className="font-mono text-[11px] text-zinc-400">{name}</span>
                            <span className={`text-[10px] ${installed ? "text-emerald-500" : "text-amber-500"}`}>
                              {installed ? "ready" : "auto-downloads"}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
        <div className="flex items-center gap-2 text-xs">
          <Activity className={`h-3.5 w-3.5 ${displayModel ? "text-purple-400/70" : "text-zinc-600"}`} />
          {displayModel ? (
            <span className="hidden md:inline font-mono text-[11px] text-purple-300/80">
              {displayModel.split("/").pop()}
            </span>
          ) : (
            <button
              onClick={onSettingsClick}
              className="font-mono text-[11px] text-zinc-500 hover:text-zinc-300 transition-colors"
            >
              No model — click to configure
            </button>
          )}
          {isOverride && (
            <span className="rounded bg-amber-950/30 px-1.5 py-0.5 text-[10px] text-amber-400 font-medium">
              override
            </span>
          )}
          {health && (
            <StatusBadge
              status={health.status}
              title={health.llm_status_detail || undefined}
            />
          )}
        </div>
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
