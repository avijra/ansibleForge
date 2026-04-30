import { useRef, useEffect } from "react";
import { X, FileCode2, ScrollText, Settings2, FileText, File } from "lucide-react";
import { cn } from "@/lib/utils";

interface FileTab {
  path: string;
  name: string;
  modified: boolean;
}

interface FileTabsProps {
  openFiles: FileTab[];
  activeFile: string | null;
  onSelect: (path: string) => void;
  onClose: (path: string) => void;
}

function tabIcon(name: string) {
  if (name.endsWith(".yml") || name.endsWith(".yaml")) return FileCode2;
  if (name.endsWith(".j2")) return ScrollText;
  if (name.endsWith(".cfg") || name.endsWith(".ini") || name.endsWith(".conf")) return Settings2;
  if (name === "hosts" || name === "extravars") return FileText;
  return File;
}

function tabIconColor(name: string) {
  if (name.endsWith(".yml") || name.endsWith(".yaml")) return "text-blue-400/70";
  if (name.endsWith(".j2")) return "text-amber-400/70";
  if (name.endsWith(".cfg") || name.endsWith(".ini")) return "text-zinc-400/70";
  if (name === "hosts") return "text-teal-400/70";
  return "text-zinc-500";
}

export function FileTabs({ openFiles, activeFile, onSelect, onClose }: FileTabsProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!scrollRef.current || !activeFile) return;
    const activeEl = scrollRef.current.querySelector(`[data-path="${CSS.escape(activeFile)}"]`);
    activeEl?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
  }, [activeFile]);

  if (openFiles.length === 0) return null;

  return (
    <div
      ref={scrollRef}
      className="flex items-stretch border-b border-zinc-800 bg-zinc-900/50 overflow-x-auto scrollbar-none"
    >
      {openFiles.map((file) => {
        const Icon = tabIcon(file.name);
        const isActive = file.path === activeFile;
        return (
          <div
            key={file.path}
            data-path={file.path}
            className={cn(
              "group flex items-center gap-1.5 px-3 py-1.5 text-xs border-r border-zinc-800/50 cursor-pointer shrink-0 transition-colors",
              isActive
                ? "bg-zinc-950 text-zinc-200 border-b-2 border-b-blue-400"
                : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-900 border-b-2 border-b-transparent"
            )}
            onClick={() => onSelect(file.path)}
          >
            <Icon className={cn("h-3.5 w-3.5 shrink-0", tabIconColor(file.name))} />
            <span className="truncate max-w-[120px]">{file.name}</span>
            {file.modified && (
              <span className="h-1.5 w-1.5 rounded-full bg-blue-400 shrink-0" />
            )}
            <button
              onClick={(e) => {
                e.stopPropagation();
                onClose(file.path);
              }}
              className={cn(
                "rounded p-0.5 transition-colors shrink-0",
                isActive
                  ? "text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800"
                  : "text-transparent group-hover:text-zinc-600 hover:!text-zinc-300 hover:bg-zinc-800"
              )}
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
