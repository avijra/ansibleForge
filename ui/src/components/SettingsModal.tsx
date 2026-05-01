import {
  X,
  Key,
  RotateCcw,
  Check,
  AlertCircle,
  Loader2,
  Cpu,
  Globe,
} from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { HealthResponse, LLMSettings, LLMSettingsUpdate } from "@/api/types";
import { cn } from "@/lib/utils";

interface SettingsModalProps {
  health: HealthResponse | null;
  llmSettings: LLMSettings | null;
  llmLoading: boolean;
  llmError: string | null;
  onLLMUpdate: (patch: LLMSettingsUpdate) => Promise<void>;
  onLLMReset: () => Promise<void>;
  onClose: () => void;
}

export function SettingsModal({
  health,
  llmSettings,
  llmLoading,
  llmError,
  onLLMUpdate,
  onLLMReset,
  onClose,
}: SettingsModalProps) {
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiBase, setApiBase] = useState("");
  const [temperature, setTemperature] = useState(0.1);
  const [maxTokens, setMaxTokens] = useState(16384);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!llmSettings) return;
    setProvider(llmSettings.provider || "");
    setModel(llmSettings.model || "");
    setApiBase(llmSettings.api_base || "");
    setTemperature(llmSettings.temperature);
    setMaxTokens(llmSettings.max_tokens);
  }, [llmSettings]);

  const handleSave = async () => {
    if (!provider.trim() || !model.trim()) return;

    const patch: LLMSettingsUpdate = {
      provider: provider.trim(),
      model: model.trim(),
    };
    if (apiKey) patch.api_key = apiKey;
    if (apiBase.trim()) patch.api_base = apiBase.trim();
    if (showAdvanced) {
      patch.temperature = temperature;
      patch.max_tokens = maxTokens;
    }

    try {
      await onLLMUpdate(patch);
      setApiKey("");
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      // error surfaced via llmError
    }
  };

  const handleReset = async () => {
    await onLLMReset();
    setApiKey("");
  };

  const dialogRef = useRef<HTMLDivElement>(null);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    },
    [onClose]
  );

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown);
    dialogRef.current?.focus();
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true" aria-label="Model Configuration">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      <div ref={dialogRef} tabIndex={-1} className="relative flex w-full max-w-md max-h-[85vh] flex-col rounded-xl border border-zinc-800 bg-zinc-900 shadow-2xl outline-none">
        <div className="flex items-center justify-between border-b border-zinc-800 px-5 py-4">
          <h2 className="text-sm font-semibold">Model Configuration</h2>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200 transition-colors"
            aria-label="Close settings"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* Recommended models */}
          <div className="rounded-lg border border-zinc-700/50 bg-zinc-800/30 px-3.5 py-3 space-y-2">
            <p className="text-[11px] font-medium text-zinc-300">Recommended Models</p>
            <p className="text-[10px] leading-relaxed text-zinc-500">
              For best results use <span className="text-zinc-300 font-mono">deepseek/deepseek-chat</span> (DeepSeek V4 Flash).
              Other good options:
            </p>
            <div className="flex flex-wrap gap-1.5">
              {[
                { provider: "deepseek", model: "deepseek/deepseek-chat", label: "DeepSeek V4 Flash" },
                { provider: "groq", model: "groq/llama-3.3-70b-versatile", label: "Llama 3.3 70B" },
                { provider: "ollama", model: "ollama/qwen2.5:32b", label: "Qwen 2.5 32B" },
                { provider: "mistral", model: "mistral/mistral-large-latest", label: "Mistral Large" },
                { provider: "openrouter", model: "openrouter/deepseek/deepseek-chat-v3-0324", label: "DeepSeek via OpenRouter" },
              ].map((m) => (
                <button
                  key={m.model}
                  onClick={() => { setProvider(m.provider); setModel(m.model); }}
                  className="rounded-md border border-zinc-700/50 bg-zinc-900/50 px-2 py-1 text-[10px] text-zinc-400 hover:border-zinc-600 hover:text-zinc-200 transition-colors"
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>

          {/* Provider */}
          <Field
            label="Provider"
            hint="e.g. deepseek, openai, anthropic, groq, mistral, ollama, openrouter, together_ai, google, azure"
            icon={<Globe className="h-3.5 w-3.5" />}
          >
            <input
              type="text"
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              placeholder="deepseek"
              className="w-full rounded-lg border border-zinc-700 bg-zinc-950 py-2.5 pl-9 pr-3 text-sm text-zinc-200 placeholder-zinc-600 outline-none focus:border-zinc-500 transition-colors"
            />
          </Field>

          {/* Model */}
          <Field
            label="Model"
            hint="The full model identifier, e.g. deepseek/deepseek-chat, groq/llama-3.3-70b-versatile, ollama/qwen2.5:32b"
            icon={<Cpu className="h-3.5 w-3.5" />}
          >
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={provider ? `${provider}/model-name` : "deepseek/deepseek-chat"}
              className="w-full rounded-lg border border-zinc-700 bg-zinc-950 py-2.5 pl-9 pr-3 text-sm font-mono text-zinc-200 placeholder-zinc-600 outline-none focus:border-zinc-500 transition-colors"
            />
          </Field>

          {/* API Key */}
          <Field
            label="API Key"
            hint="Stored in server memory only — never persisted to disk or sent to the AI model"
            icon={<Key className="h-3.5 w-3.5" />}
          >
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={
                llmSettings?.api_key_set
                  ? "Key is set — enter a new one to change"
                  : "Enter your API key"
              }
              className="w-full rounded-lg border border-zinc-700 bg-zinc-950 py-2.5 pl-9 pr-3 text-sm font-mono text-zinc-200 placeholder-zinc-600 outline-none focus:border-zinc-500 transition-colors"
            />
            {llmSettings?.api_key_set && !apiKey && (
              <p className="mt-1.5 flex items-center gap-1 text-[11px] text-emerald-400">
                <Check className="h-3 w-3" /> API key configured
              </p>
            )}
          </Field>

          {/* API Base URL (optional, for self-hosted / Ollama / vLLM) */}
          <Field
            label="API Base URL (optional)"
            hint="Only needed for self-hosted models like Ollama, vLLM, or custom endpoints"
            icon={<Globe className="h-3.5 w-3.5" />}
          >
            <input
              type="text"
              value={apiBase}
              onChange={(e) => setApiBase(e.target.value)}
              placeholder="http://localhost:11434"
              className="w-full rounded-lg border border-zinc-700 bg-zinc-950 py-2.5 pl-9 pr-3 text-sm font-mono text-zinc-200 placeholder-zinc-600 outline-none focus:border-zinc-500 transition-colors"
            />
          </Field>

          {/* Advanced toggle */}
          <button
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="text-[11px] text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            {showAdvanced ? "▾" : "▸"} Advanced parameters
          </button>

          {showAdvanced && (
            <div className="space-y-4 rounded-lg border border-zinc-800 bg-zinc-950/50 p-4">
              <div>
                <label className="mb-1 flex items-center justify-between text-[11px] text-zinc-400">
                  <span>Temperature</span>
                  <span className="font-mono text-zinc-300">{temperature.toFixed(2)}</span>
                </label>
                <input
                  type="range"
                  min={0}
                  max={2}
                  step={0.05}
                  value={temperature}
                  onChange={(e) => setTemperature(parseFloat(e.target.value))}
                  className="w-full accent-zinc-500"
                />
                <div className="mt-0.5 flex justify-between text-[10px] text-zinc-600">
                  <span>Precise</span>
                  <span>Creative</span>
                </div>
              </div>
              <div>
                <label className="mb-1 block text-[11px] text-zinc-400">
                  Max output tokens
                </label>
                <input
                  type="number"
                  min={1}
                  max={128000}
                  value={maxTokens}
                  onChange={(e) => setMaxTokens(parseInt(e.target.value) || 16384)}
                  className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-xs font-mono text-zinc-200 outline-none focus:border-zinc-500 transition-colors"
                />
              </div>
            </div>
          )}

          {/* Error */}
          {llmError && (
            <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/5 px-3 py-2.5 text-xs text-red-300">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {llmError}
            </div>
          )}

          {/* Active config summary */}
          {llmSettings && llmSettings.source === "runtime" && (
            <div className="rounded-lg border border-zinc-700 bg-zinc-800/30 px-3 py-2.5 text-[11px] text-zinc-300">
              Active: <span className="font-mono font-medium">{llmSettings.provider}/{llmSettings.model}</span>
            </div>
          )}

          {/* Connection Status */}
          <hr className="border-zinc-800" />
          <div className="space-y-1.5 text-xs">
            <div className="mb-1.5 font-medium text-zinc-300">Status</div>
            {health ? (
              <>
                <Row label="Backend" value={health.status} />
                <Row label="Version" value={health.version} />
                <Row label="Tools" value={`${health.tools_available.length} available`} />
              </>
            ) : (
              <p className="text-zinc-500">Unable to connect to the backend.</p>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-zinc-800 px-5 py-3">
          <button
            onClick={handleReset}
            disabled={llmLoading || llmSettings?.source === "env"}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              llmSettings?.source === "env"
                ? "text-zinc-700 cursor-not-allowed"
                : "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            )}
          >
            <RotateCcw className="h-3 w-3" />
            Reset
          </button>

          <button
            onClick={handleSave}
            disabled={llmLoading || !provider.trim() || !model.trim()}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-5 py-2 text-xs font-medium transition-all",
              llmLoading || !provider.trim() || !model.trim()
                ? "bg-zinc-800 text-zinc-600 cursor-not-allowed"
                : saved
                  ? "bg-emerald-600 text-white"
                  : "bg-zinc-600 text-white hover:bg-zinc-500"
            )}
          >
            {llmLoading ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : saved ? (
              <Check className="h-3 w-3" />
            ) : null}
            {saved ? "Saved" : "Apply"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  icon,
  children,
}: {
  label: string;
  hint?: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-xs font-medium text-zinc-300">
        {label}
      </label>
      <div className="relative">
        <div className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-600">
          {icon}
        </div>
        {children}
      </div>
      {hint && (
        <p className="mt-1 text-[10px] leading-relaxed text-zinc-600">{hint}</p>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-zinc-500">{label}</span>
      <span className="font-mono text-zinc-300">{value}</span>
    </div>
  );
}
