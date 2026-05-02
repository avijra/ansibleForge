import { useState } from "react";
import { KeyRound, Lock, Eye, EyeOff, Send, CheckCircle2, X } from "lucide-react";
import type { AgentEvent } from "@/api/types";
import { api } from "@/api/client";

interface SecretRequestEventProps {
  event: AgentEvent;
  onSkip?: () => void;
}

export function SecretRequestEvent({ event, onSkip }: SecretRequestEventProps) {
  const secretName = (event.data.secret_name as string) || "secret";
  const description = (event.data.secret_description as string) || "";
  const sensitiveType = (event.data.sensitive_type as string) || "other";
  const sessionId = (event.data.session_id as string) || null;

  const [value, setValue] = useState("");
  const [showValue, setShowValue] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [skipped, setSkipped] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isMultiline = sensitiveType === "json" || sensitiveType === "key" || sensitiveType === "certificate";

  const handleSubmit = async () => {
    if (!value.trim() || !sessionId) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.secrets.submit(sessionId, secretName, value, description);
      setSubmitted(true);
      setValue("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit secret");
    } finally {
      setSubmitting(false);
    }
  };

  const handleSkip = () => {
    setSkipped(true);
    onSkip?.();
  };

  if (submitted) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-emerald-800/20 bg-zinc-900/40 px-3 py-1.5">
        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
        <span className="text-xs font-medium text-emerald-400">Secret stored</span>
        <code className="rounded bg-emerald-900/30 px-1.5 py-0.5 text-[10px] font-mono text-emerald-500/80">{secretName}</code>
      </div>
    );
  }

  if (skipped) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-zinc-800/40 bg-zinc-900/40 px-3 py-1.5">
        <X className="h-3.5 w-3.5 text-zinc-500" />
        <span className="text-xs font-medium text-zinc-500">Secret skipped</span>
        <code className="rounded bg-zinc-800/60 px-1.5 py-0.5 text-[10px] font-mono text-zinc-600">{secretName}</code>
      </div>
    );
  }

  return (
    <div className="animate-slide-in rounded-lg border border-cyan-800/30 bg-cyan-950/15 shadow-[0_0_12px_-4px_rgba(6,182,212,0.12)] p-3 space-y-2">
      <div className="flex items-center gap-2">
        <KeyRound className="h-3.5 w-3.5 text-zinc-400" />
        <span className="text-xs font-semibold text-zinc-200">Secret Required</span>
        <code className="rounded-full bg-zinc-800 px-1.5 py-0.5 text-[10px] font-mono text-zinc-400">{secretName}</code>
        <Lock className="h-2.5 w-2.5 text-zinc-600 ml-auto" />
      </div>

      {description && (
        <p className="text-[11px] text-zinc-500 leading-snug">{description}</p>
      )}

      <div className="flex items-center gap-1.5">
        {isMultiline ? (
          <div className="relative flex-1">
            <textarea
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder={`Paste ${secretName}...`}
              rows={3}
              className="w-full rounded-md border border-zinc-700 bg-zinc-900/80 px-2.5 py-2 text-xs font-mono text-zinc-200 placeholder-zinc-600 focus:border-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-500/50 resize-none"
              style={showValue ? {} : { WebkitTextSecurity: "disc" } as React.CSSProperties}
            />
            <button
              type="button"
              onClick={() => setShowValue(!showValue)}
              className="absolute top-2 right-2 text-zinc-500 hover:text-zinc-300 transition-colors"
            >
              {showValue ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
            </button>
          </div>
        ) : (
          <div className="relative flex-1">
            <input
              type={showValue ? "text" : "password"}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder={`Enter ${secretName}...`}
              onKeyDown={(e) => { if (e.key === "Enter") handleSubmit(); }}
              className="w-full rounded-md border border-zinc-700 bg-zinc-900/80 px-2.5 py-1.5 pr-14 text-xs font-mono text-zinc-200 placeholder-zinc-600 focus:border-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-500/50"
            />
            <button
              type="button"
              onClick={() => setShowValue(!showValue)}
              className="absolute top-1/2 right-8 -translate-y-1/2 text-zinc-500 hover:text-zinc-300 transition-colors"
            >
              {showValue ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
            </button>
          </div>
        )}
        <button
          onClick={handleSubmit}
          disabled={!value.trim() || submitting}
          className="inline-flex items-center gap-1 rounded-md bg-zinc-700 px-3 py-1.5 text-xs font-medium text-zinc-100 hover:bg-zinc-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
        >
          <Send className="h-3 w-3" />
          {submitting ? "..." : "Submit"}
        </button>
        <button
          onClick={handleSkip}
          className="inline-flex items-center rounded-md border border-zinc-700 px-2 py-1.5 text-xs text-zinc-400 hover:text-zinc-200 hover:border-zinc-500 transition-colors shrink-0"
        >
          <X className="h-3 w-3" />
        </button>
      </div>

      {error && <p className="text-[11px] text-red-400">{error}</p>}
    </div>
  );
}
