import { Send, Square } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { cn } from "@/lib/utils";

interface ChatInputProps {
  onSend: (message: string) => void;
  onCancel: () => void;
  isStreaming: boolean;
  disabled?: boolean;
  draft?: string;
  onDraftConsumed?: () => void;
}

export function ChatInput({ onSend, onCancel, isStreaming, disabled, draft, onDraftConsumed }: ChatInputProps) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

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

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed || isStreaming) return;
    onSend(trimmed);
    setValue("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div>
      <div className="flex items-end gap-2 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 focus-within:border-teal-500/50 transition-colors">
        <textarea
          ref={inputRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Describe what you want to automate..."
          disabled={disabled || isStreaming}
          rows={1}
          aria-label="Chat message input"
          className={cn(
            "flex-1 resize-none bg-transparent text-sm text-zinc-100 placeholder-zinc-600 outline-none",
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
                ? "text-teal-400 hover:bg-teal-500/10 hover:text-teal-300"
                : "text-zinc-600 cursor-not-allowed"
            )}
            title="Send"
            aria-label="Send message"
          >
            <Send className="h-4 w-4" />
          </button>
        )}
      </div>
      <p className="mt-1.5 text-center text-[10px] text-zinc-700">
        Enter to send &middot; Shift+Enter for new line &middot; All executions require approval
      </p>
    </div>
  );
}
