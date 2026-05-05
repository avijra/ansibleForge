import { Send, Square, Server, Box, FileCode2, Terminal, Hash, File } from "lucide-react";
import { useState, useRef, useEffect, useCallback } from "react";
import { cn } from "@/lib/utils";
import type { Suggestion } from "@/hooks/useAnsibleContext";

interface ChatInputProps {
  onSend: (message: string) => void;
  onCancel: () => void;
  isStreaming: boolean;
  disabled?: boolean;
  draft?: string;
  onDraftConsumed?: () => void;
  suggestions?: Suggestion[];
  getFiltered?: (prefix: string, trigger: "@" | "/") => Suggestion[];
}

function suggestionIcon(type: Suggestion["type"]) {
  switch (type) {
    case "host": return Server;
    case "module": return Box;
    case "role": return FileCode2;
    case "playbook": return FileCode2;
    case "file": return File;
    case "command": return Terminal;
    default: return Hash;
  }
}

function suggestionColor(type: Suggestion["type"]) {
  switch (type) {
    case "host": return "text-teal-400";
    case "module": return "text-blue-400";
    case "role": return "text-purple-400";
    case "playbook": return "text-amber-400";
    case "file": return "text-zinc-400";
    case "command": return "text-emerald-400";
    default: return "text-zinc-400";
  }
}

export function ChatInput({
  onSend,
  onCancel,
  isStreaming,
  disabled,
  draft,
  onDraftConsumed,
  getFiltered,
}: ChatInputProps) {
  const [value, setValue] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [filteredSuggestions, setFilteredSuggestions] = useState<Suggestion[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [triggerInfo, setTriggerInfo] = useState<{ trigger: "@" | "/"; startPos: number } | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const suggestionsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    if (draft) {
      setValue(draft);
      onDraftConsumed?.();
      inputRef.current?.focus();
    }
  }, [draft, onDraftConsumed]);

  const updateSuggestions = useCallback(
    (text: string, cursorPos: number) => {
      if (!getFiltered) {
        setShowSuggestions(false);
        return;
      }

      const before = text.slice(0, cursorPos);
      const atMatch = before.match(/@(\w*)$/);
      const slashMatch = before.match(/^\/(\w*)$/);

      if (atMatch) {
        const results = getFiltered(atMatch[1], "@");
        setFilteredSuggestions(results);
        setShowSuggestions(results.length > 0);
        setSelectedIndex(0);
        setTriggerInfo({ trigger: "@", startPos: cursorPos - atMatch[0].length });
      } else if (slashMatch) {
        const results = getFiltered(slashMatch[1], "/");
        setFilteredSuggestions(results);
        setShowSuggestions(results.length > 0);
        setSelectedIndex(0);
        setTriggerInfo({ trigger: "/", startPos: 0 });
      } else {
        setShowSuggestions(false);
        setTriggerInfo(null);
      }
    },
    [getFiltered]
  );

  const applySuggestion = useCallback(
    (suggestion: Suggestion) => {
      if (!triggerInfo) return;
      const before = value.slice(0, triggerInfo.startPos);
      const afterCursor = value.slice(inputRef.current?.selectionStart ?? value.length);

      let insertion: string;
      if (triggerInfo.trigger === "/") {
        insertion = suggestion.label + " ";
      } else {
        insertion = "@" + suggestion.label + " ";
      }

      const newValue = before + insertion + afterCursor;
      setValue(newValue);
      setShowSuggestions(false);
      setTriggerInfo(null);

      requestAnimationFrame(() => {
        if (inputRef.current) {
          const pos = before.length + insertion.length;
          inputRef.current.selectionStart = pos;
          inputRef.current.selectionEnd = pos;
          inputRef.current.focus();
        }
      });
    },
    [triggerInfo, value]
  );

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed || isStreaming) return;
    onSend(trimmed);
    setValue("");
    setShowSuggestions(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (showSuggestions && filteredSuggestions.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((i) => (i + 1) % filteredSuggestions.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((i) => (i - 1 + filteredSuggestions.length) % filteredSuggestions.length);
        return;
      }
      if (e.key === "Tab" || e.key === "Enter") {
        if (showSuggestions) {
          e.preventDefault();
          applySuggestion(filteredSuggestions[selectedIndex]);
          return;
        }
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setShowSuggestions(false);
        return;
      }
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newValue = e.target.value;
    setValue(newValue);
    updateSuggestions(newValue, e.target.selectionStart ?? newValue.length);
  };

  return (
    <div className="relative">
      {showSuggestions && filteredSuggestions.length > 0 && (
        <div
          ref={suggestionsRef}
          className="absolute bottom-full left-0 right-0 mb-1 max-h-48 overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-900 shadow-xl shadow-black/40 z-50"
        >
          {filteredSuggestions.map((s, i) => {
            const Icon = suggestionIcon(s.type);
            return (
              <button
                key={`${s.type}-${s.label}`}
                onMouseDown={(e) => {
                  e.preventDefault();
                  applySuggestion(s);
                }}
                className={cn(
                  "flex items-center gap-2 w-full px-3 py-1.5 text-left text-xs transition-colors",
                  i === selectedIndex
                    ? "bg-zinc-800 text-zinc-100"
                    : "text-zinc-400 hover:bg-zinc-800/50"
                )}
              >
                <Icon className={cn("h-3.5 w-3.5 shrink-0", suggestionColor(s.type))} />
                <span className="font-mono">{s.label}</span>
                {s.detail && (
                  <span className="ml-auto text-[10px] text-zinc-600">{s.detail}</span>
                )}
              </button>
            );
          })}
        </div>
      )}

      <div className="flex items-end gap-2 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 focus-within:border-zinc-500/50 transition-colors">
        <textarea
          ref={inputRef}
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder="Describe what you want to automate... (@ for hosts/modules, / for commands)"
          disabled={disabled || isStreaming}
          rows={1}
          aria-label="Chat message input"
          className={cn(
            "flex-1 resize-none bg-transparent font-mono text-sm text-zinc-100 placeholder-zinc-600 outline-none",
            "min-h-[20px] max-h-32"
          )}
          style={{
            height: "auto",
            overflow: "hidden",
          }}
          onInput={(e) => {
            const target = e.target as HTMLTextAreaElement;
            target.style.height = "auto";
            target.style.height = `${Math.min(target.scrollHeight, 128)}px`;
          }}
        />
        {isStreaming ? (
          <button
            onClick={onCancel}
            className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200 transition-colors"
            title="Stop"
            aria-label="Stop generation"
          >
            <Square className="h-4 w-4" />
          </button>
        ) : (
          <button
            onClick={handleSubmit}
            disabled={!value.trim()}
            className={cn(
              "rounded-md p-1.5 transition-colors",
              value.trim()
                ? "text-zinc-300 hover:bg-zinc-800 hover:text-zinc-100"
                : "text-zinc-600 cursor-not-allowed"
            )}
            title="Send (Enter)"
            aria-label="Send message"
          >
            <Send className="h-4 w-4" />
          </button>
        )}
      </div>
      <p className="mt-1.5 text-center text-[10px] text-zinc-700">
        Enter to send &middot; Shift+Enter for new line &middot; @ mentions &middot; / commands &middot; ⌘K palette
      </p>
    </div>
  );
}
