import {
  AlertCircle,
  AlertTriangle,
  Box,
  Check,
  ChevronDown,
  Cpu,
  Globe,
  Key,
  Loader2,
  RotateCcw,
  X,
} from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { api } from "@/api/client";
import type {
  ApprovedModel,
  HealthResponse,
  LLMSettings,
  LLMSettingsUpdate,
} from "@/api/types";
import { useExecutionSettings } from "@/hooks/useExecutionSettings";
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

const TIER_LABELS: Record<string, string> = {
  $: "~$0.02/session",
  $$: "~$0.20–$0.60/session",
  $$$: "~$0.80–$1.50/session",
  $$$$: "~$5/session",
};

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
  const [showCustom, setShowCustom] = useState(false);
  const [saved, setSaved] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [testing, setTesting] = useState(false);
  const [approvedModels, setApprovedModels] = useState<ApprovedModel[]>([]);

  useEffect(() => {
    api.llmSettings.models().then(setApprovedModels).catch(() => {});
  }, []);

  useEffect(() => {
    if (!llmSettings) return;
    setProvider(llmSettings.provider || "");
    setModel(llmSettings.model || "");
    setApiBase(llmSettings.api_base || "");
    setTemperature(llmSettings.temperature);
    setMaxTokens(llmSettings.max_tokens);

    const isApproved = approvedModels.some(
      (m) => m.model === llmSettings.model
    );
    if (llmSettings.model && !isApproved && llmSettings.source === "runtime") {
      setShowCustom(true);
    }
  }, [llmSettings, approvedModels]);

  const selectModel = (m: ApprovedModel) => {
    setProvider(m.provider);
    setModel(m.model);
    setShowCustom(false);
    setTestResult(null);
  };

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
    setShowCustom(false);
  };

  const handleTest = async () => {
    if (!model.trim()) return;
    setTesting(true);
    setTestResult(null);
    try {
      const body: LLMSettingsUpdate = { model: model.trim(), provider: provider.trim() };
      if (apiKey) body.api_key = apiKey;
      if (apiBase.trim()) body.api_base = apiBase.trim();
      const res = await api.llmSettings.test(body);
      setTestResult(res.ok
        ? { ok: true, message: `Connected — model replied: "${res.reply}"` }
        : { ok: false, message: res.error || "Connection failed." }
      );
    } catch (err) {
      setTestResult({ ok: false, message: String(err) });
    } finally {
      setTesting(false);
    }
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

  const isCustomModel =
    model.trim() !== "" &&
    !approvedModels.some((m) => m.model === model.trim());

  const needsApiBase =
    provider === "deepseek" || provider === "ollama" || showCustom;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      role="dialog"
      aria-modal="true"
      aria-label="Model Configuration"
    >
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={dialogRef}
        tabIndex={-1}
        className="relative flex w-full max-w-md max-h-[85vh] flex-col rounded-xl border border-zinc-800 bg-zinc-900 shadow-2xl outline-none"
      >
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
          {/* Guidance */}
          <p className="text-[11px] leading-relaxed text-zinc-400">
            Choose a model. Tuyere works best with these tested models. Start
            with{" "}
            <span className="text-zinc-200 font-medium">Claude Sonnet 4</span>{" "}
            for the best balance of quality and cost, or{" "}
            <span className="text-zinc-200 font-medium">DeepSeek V4-Pro</span>{" "}
            if cost matters most.
          </p>

          {/* Model cards */}
          <div className="space-y-1.5">
            {approvedModels.map((m) => (
              <button
                key={m.model}
                onClick={() => selectModel(m)}
                className={cn(
                  "w-full rounded-lg border px-3.5 py-3 text-left transition-all",
                  model === m.model
                    ? "border-zinc-500 bg-zinc-800/80 ring-1 ring-zinc-500/30"
                    : "border-zinc-700/50 bg-zinc-800/20 hover:border-zinc-600 hover:bg-zinc-800/40"
                )}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-zinc-200">
                      {m.label}
                    </span>
                    <span className="rounded bg-zinc-700/50 px-1.5 py-0.5 text-[9px] font-mono text-zinc-400">
                      {m.tier}
                    </span>
                  </div>
                  {model === m.model && (
                    <Check className="h-3.5 w-3.5 text-emerald-400" />
                  )}
                </div>
                <p className="mt-1 text-[10px] text-zinc-500">
                  {m.description}
                </p>
                <p className="mt-0.5 text-[9px] text-zinc-600">
                  {TIER_LABELS[m.tier] || m.tier} &middot;{" "}
                  <span className="font-mono">{m.model}</span>
                </p>
              </button>
            ))}
          </div>

          {/* Custom model toggle */}
          <button
            onClick={() => setShowCustom(!showCustom)}
            className="flex items-center gap-1.5 text-[11px] text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            <ChevronDown
              className={cn(
                "h-3 w-3 transition-transform",
                showCustom && "rotate-180"
              )}
            />
            Use a custom model
          </button>

          {showCustom && (
            <div className="space-y-4 rounded-lg border border-amber-500/20 bg-amber-500/5 p-4">
              <div className="flex items-start gap-2 text-[11px] text-amber-300/80">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>
                  Custom models have not been tested with Tuyere. Tool calling,
                  safety rules, and multi-step reliability may be degraded.
                </span>
              </div>

              <Field
                label="Provider"
                hint="e.g. deepseek, openai, anthropic, ollama, together_ai, google"
                icon={<Globe className="h-3.5 w-3.5" />}
              >
                <input
                  type="text"
                  value={provider}
                  onChange={(e) => setProvider(e.target.value)}
                  placeholder="provider-name"
                  className="w-full rounded-lg border border-zinc-700 bg-zinc-950 py-2.5 pl-9 pr-3 text-sm text-zinc-200 placeholder-zinc-600 outline-none focus:border-zinc-500 transition-colors"
                />
              </Field>

              <Field
                label="Model"
                hint="The full model identifier, e.g. provider/model-name"
                icon={<Cpu className="h-3.5 w-3.5" />}
              >
                <input
                  type="text"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  placeholder={
                    provider
                      ? `${provider}/model-name`
                      : "provider/model-name"
                  }
                  className="w-full rounded-lg border border-zinc-700 bg-zinc-950 py-2.5 pl-9 pr-3 text-sm font-mono text-zinc-200 placeholder-zinc-600 outline-none focus:border-zinc-500 transition-colors"
                />
              </Field>
            </div>
          )}

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

          {/* API Base URL — contextual */}
          {needsApiBase && (
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
          )}

          {/* Advanced toggle */}
          <button
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-1.5 text-[11px] text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            <ChevronDown
              className={cn(
                "h-3 w-3 transition-transform",
                showAdvanced && "rotate-180"
              )}
            />
            Advanced parameters
          </button>

          {showAdvanced && (
            <div className="space-y-4 rounded-lg border border-zinc-800 bg-zinc-950/50 p-4">
              <div>
                <label className="mb-1 flex items-center justify-between text-[11px] text-zinc-400">
                  <span>Temperature</span>
                  <span className="font-mono text-zinc-300">
                    {temperature.toFixed(2)}
                  </span>
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
                  onChange={(e) =>
                    setMaxTokens(parseInt(e.target.value) || 16384)
                  }
                  className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-xs font-mono text-zinc-200 outline-none focus:border-zinc-500 transition-colors"
                />
              </div>
            </div>
          )}

          {/* Warning for custom model */}
          {isCustomModel && !showCustom && model.trim() && (
            <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2.5 text-xs text-amber-300">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              Untested model — reliability may be degraded.
            </div>
          )}

          {/* Server warning from API */}
          {llmSettings?.warning && (
            <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2.5 text-xs text-amber-300">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {llmSettings.warning}
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
              Active:{" "}
              <span className="font-mono font-medium">
                {llmSettings.provider}/{llmSettings.model}
              </span>
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
                <Row
                  label="Tools"
                  value={`${health.tools_available.length} available`}
                />
                <Row
                  label="Execution"
                  value={health.execution_mode === "container" ? "Container (EE)" : "Host"}
                />
              </>
            ) : (
              <p className="text-zinc-500">
                Unable to connect to the backend.
              </p>
            )}
          </div>

          {/* Execution Environment */}
          <hr className="border-zinc-800" />
          <ExecutionSection />
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
            onClick={handleTest}
            disabled={testing || !model.trim()}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-4 py-2 text-xs font-medium transition-all",
              testing || !model.trim()
                ? "bg-zinc-800 text-zinc-600 cursor-not-allowed"
                : testResult?.ok
                  ? "bg-emerald-900/40 text-emerald-400 border border-emerald-800/30"
                  : "bg-zinc-800/60 text-zinc-400 border border-zinc-700/50 hover:border-zinc-600"
            )}
          >
            {testing ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
            {testing ? "Testing..." : "Test"}
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
        {testResult && (
          <div className={cn(
            "mt-2 rounded-md px-3 py-2 text-xs",
            testResult.ok
              ? "bg-emerald-900/20 text-emerald-400 border border-emerald-800/20"
              : "bg-red-900/20 text-red-400 border border-red-800/20"
          )}>
            {testResult.ok ? <Check className="inline h-3 w-3 mr-1" /> : <AlertCircle className="inline h-3 w-3 mr-1" />}
            {testResult.message}
          </div>
        )}
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
      <label
        htmlFor={id}
        className="mb-1.5 block text-xs font-medium text-zinc-300"
      >
        {label}
      </label>
      <div className="relative">
        <div className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-600">
          {icon}
        </div>
        {children}
      </div>
      {hint && (
        <p className="mt-1 text-[10px] leading-relaxed text-zinc-600">
          {hint}
        </p>
      )}
    </div>
  );
}

function ExecutionSection() {
  const { settings, loading, update } = useExecutionSettings();
  const [image, setImage] = useState("");
  const [runtime, setRuntime] = useState("docker");

  useEffect(() => {
    if (!settings) return;
    setImage(settings.image);
    setRuntime(settings.container_runtime);
  }, [settings]);

  const handleToggle = async () => {
    if (!settings) return;
    await update({ enabled: !settings.enabled });
  };

  const handleSaveEE = async () => {
    await update({ image: image.trim(), container_runtime: runtime });
  };

  if (!settings) return null;

  return (
    <div className="space-y-3 text-xs">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Box className="h-3.5 w-3.5 text-zinc-500" />
          <span className="font-medium text-zinc-300">Execution Environment</span>
        </div>
        <button
          onClick={handleToggle}
          disabled={loading}
          className={cn(
            "relative h-5 w-9 rounded-full transition-colors",
            settings.enabled ? "bg-emerald-600" : "bg-zinc-700"
          )}
          role="switch"
          aria-checked={settings.enabled}
          aria-label="Toggle container execution"
        >
          <span
            className={cn(
              "absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform",
              settings.enabled && "translate-x-4"
            )}
          />
        </button>
      </div>

      <p className="text-[10px] text-zinc-500 leading-relaxed">
        When enabled, all Ansible, Terraform, and Git commands run inside an isolated container
        instead of on the host machine.
      </p>

      {settings.enabled && (
        <div className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-950/50 p-3">
          <div>
            <label className="mb-1 block text-[11px] text-zinc-400">Container Image</label>
            <input
              type="text"
              value={image}
              onChange={(e) => setImage(e.target.value)}
              className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-xs font-mono text-zinc-200 outline-none focus:border-zinc-500 transition-colors"
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] text-zinc-400">Container Runtime</label>
            <select
              value={runtime}
              onChange={(e) => setRuntime(e.target.value)}
              className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-xs text-zinc-200 outline-none focus:border-zinc-500 transition-colors"
            >
              <option value="docker">Docker</option>
              <option value="podman">Podman</option>
            </select>
          </div>
          <div className="flex items-center gap-1.5 text-[10px]">
            {settings.runtime_available ? (
              <span className="flex items-center gap-1 text-emerald-400">
                <Check className="h-3 w-3" /> {runtime} available
              </span>
            ) : (
              <span className="flex items-center gap-1 text-red-400">
                <AlertCircle className="h-3 w-3" /> {runtime} not found
              </span>
            )}
          </div>
          <button
            onClick={handleSaveEE}
            disabled={loading}
            className="w-full rounded-md bg-zinc-700 px-3 py-1.5 text-[11px] font-medium text-zinc-200 hover:bg-zinc-600 transition-colors disabled:opacity-50"
          >
            {loading ? "Saving..." : "Save Execution Settings"}
          </button>
        </div>
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
