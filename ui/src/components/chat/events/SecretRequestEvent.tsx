import { useState } from "react";
import { KeyRound, Lock, Eye, EyeOff, Send, CheckCircle2 } from "lucide-react";
import type { AgentEvent } from "@/api/types";
import { api } from "@/api/client";

interface SecretRequestEventProps {
  event: AgentEvent;
}

export function SecretRequestEvent({ event }: SecretRequestEventProps) {
  const secretName = (event.data.secret_name as string) || "secret";
  const description = (event.data.secret_description as string) || "";
  const sensitiveType = (event.data.sensitive_type as string) || "other";
  const sessionId = (event.data.session_id as string) || null;

  const [value, setValue] = useState("");
  const [showValue, setShowValue] = useState(false);
  const [submitted, setSubmitted] = useState(false);
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

  if (submitted) {
    return (
      <div className="animate-slide-in rounded-lg border border-emerald-800/50 bg-emerald-950/20 p-4">
        <div className="flex items-center gap-2.5">
          <CheckCircle2 className="h-4 w-4 text-emerald-400" />
          <span className="text-sm font-medium text-emerald-300">
            Secret <code className="rounded bg-emerald-900/40 px-1.5 py-0.5 text-xs font-mono">{secretName}</code> securely stored
          </span>
        </div>
        <p className="mt-1.5 text-xs text-emerald-500/70 pl-6">
          Value encrypted in session vault. It will be injected at execution time and is never sent to the AI model.
        </p>
      </div>
    );
  }

  return (
    <div className="animate-slide-in rounded-lg border border-cyan-800/30 bg-cyan-950/15 shadow-[0_0_12px_-4px_rgba(6,182,212,0.12)] p-4 space-y-3">
      <div className="flex items-center gap-2.5">
        <div className="rounded-lg bg-zinc-800/60 p-1.5">
          <KeyRound className="h-4 w-4 text-zinc-400" />
        </div>
        <div>
          <span className="text-sm font-semibold text-zinc-200">
            Secret Required
          </span>
          <span className="ml-2 rounded-full bg-zinc-800 px-2 py-0.5 text-[10px] font-mono text-zinc-400">
            {secretName}
          </span>
        </div>
      </div>

      <p className="text-xs text-zinc-400 leading-relaxed pl-0.5">
        {description}
      </p>

      <div className="flex items-center gap-1.5 text-[10px] text-zinc-600">
        <Lock className="h-3 w-3" />
        <span>This value is stored securely in your session and never sent to the AI model</span>
      </div>

      <div className="space-y-2">
        {isMultiline ? (
          <div className="relative">
            <textarea
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder={`Paste your ${secretName} here...`}
              rows={4}
              className="w-full rounded-lg border border-zinc-700 bg-zinc-900/80 px-3 py-2.5 text-xs font-mono text-zinc-200 placeholder-zinc-600 focus:border-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-500/50 resize-none"
              style={showValue ? {} : { WebkitTextSecurity: "disc" } as React.CSSProperties}
            />
            <button
              type="button"
              onClick={() => setShowValue(!showValue)}
              className="absolute top-2.5 right-2.5 text-zinc-500 hover:text-zinc-300 transition-colors"
              title={showValue ? "Hide value" : "Show value"}
            >
              {showValue ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            </button>
          </div>
        ) : (
          <div className="relative">
            <input
              type={showValue ? "text" : "password"}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder={`Enter ${secretName}...`}
              onKeyDown={(e) => { if (e.key === "Enter") handleSubmit(); }}
              className="w-full rounded-lg border border-zinc-700 bg-zinc-900/80 px-3 py-2.5 pr-16 text-xs font-mono text-zinc-200 placeholder-zinc-600 focus:border-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-500/50"
            />
            <button
              type="button"
              onClick={() => setShowValue(!showValue)}
              className="absolute top-1/2 right-10 -translate-y-1/2 text-zinc-500 hover:text-zinc-300 transition-colors"
              title={showValue ? "Hide value" : "Show value"}
            >
              {showValue ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            </button>
          </div>
        )}

        {error && (
          <p className="text-xs text-red-400">{error}</p>
        )}

        <button
          onClick={handleSubmit}
          disabled={!value.trim() || submitting}
          className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-700 px-4 py-2 text-xs font-medium text-zinc-100 hover:bg-zinc-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <Send className="h-3.5 w-3.5" />
          {submitting ? "Submitting..." : "Submit Securely"}
        </button>
      </div>
    </div>
  );
}
