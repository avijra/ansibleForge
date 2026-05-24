import { useCallback, useState } from "react";
import { Check, X, Settings2, CheckCircle2, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AgentEvent } from "@/api/types";

interface ConfigField {
  name: string;
  label: string;
  type: "text" | "number" | "select" | "textarea" | "boolean";
  required?: boolean;
  default?: string | number | boolean;
  placeholder?: string;
  options?: string[];
}

interface ConfigRequestEventProps {
  event: AgentEvent;
  isPending: boolean;
  onApprove: () => void;
  onReject: () => void;
}

export function isConfigRequest(event: AgentEvent): boolean {
  const nested = (event.data.data as Record<string, unknown>) ?? event.data;
  return nested.config_request === true;
}

export function ConfigRequestEvent({
  event,
  isPending,
  onApprove,
  onReject,
}: ConfigRequestEventProps) {
  const nested = (event.data.data as Record<string, unknown>) ?? event.data;
  const title = (nested.title as string) || "Configuration Required";
  const fields = (nested.fields as ConfigField[]) || [];

  const initialValues: Record<string, string | number | boolean> = {};
  for (const f of fields) {
    if (f.default !== undefined) {
      initialValues[f.name] = f.default;
    } else if (f.type === "boolean") {
      initialValues[f.name] = false;
    } else if (f.type === "number") {
      initialValues[f.name] = 0;
    } else {
      initialValues[f.name] = "";
    }
  }

  const [values, setValues] = useState(initialValues);
  const [resolved, setResolved] = useState<"approved" | "rejected" | null>(
    null
  );

  const setValue = useCallback(
    (name: string, value: string | number | boolean) => {
      setValues((prev) => ({ ...prev, [name]: value }));
    },
    []
  );

  const handleSubmit = useCallback(() => {
    setResolved("approved");
    onApprove();
  }, [onApprove]);

  const handleReject = useCallback(() => {
    setResolved("rejected");
    onReject();
  }, [onReject]);

  const allRequiredFilled = fields
    .filter((f) => f.required)
    .every((f) => {
      const v = values[f.name];
      return v !== undefined && v !== "" && v !== 0;
    });

  const showForm = isPending && !resolved;
  const isResolved = resolved || !isPending;

  if (isResolved && !showForm) {
    const label = resolved === "rejected" ? "Cancelled" : "Submitted";
    const Icon = resolved === "rejected" ? XCircle : CheckCircle2;
    const color =
      resolved === "rejected" ? "text-red-400" : "text-emerald-400";
    const border =
      resolved === "rejected" ? "border-red-800/20" : "border-emerald-800/20";
    return (
      <div
        className={cn(
          "flex items-center gap-2 rounded-md border px-3 py-1.5 bg-zinc-900/40",
          border
        )}
      >
        <Icon className={cn("h-3.5 w-3.5", color)} />
        <span className={cn("text-xs font-medium", color)}>{label}</span>
        <span className="text-[10px] text-zinc-600">· {title}</span>
      </div>
    );
  }

  return (
    <div className="animate-slide-in rounded-lg border border-blue-800/30 bg-blue-950/15 shadow-[0_0_12px_-4px_rgba(59,130,246,0.12)] p-3 space-y-3">
      <div className="flex items-center gap-2">
        <Settings2 className="h-3.5 w-3.5 text-blue-400" />
        <span className="text-xs font-semibold text-blue-300">{title}</span>
      </div>

      <div className="space-y-2">
        {fields.map((field) => (
          <div key={field.name} className="space-y-0.5">
            <label className="text-[11px] text-zinc-400">
              {field.label}
              {field.required && (
                <span className="text-red-400 ml-0.5">*</span>
              )}
            </label>
            {field.type === "text" && (
              <input
                type="text"
                value={String(values[field.name] ?? "")}
                onChange={(e) => setValue(field.name, e.target.value)}
                placeholder={field.placeholder}
                className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-200 placeholder-zinc-600 focus:border-blue-500 focus:outline-none"
              />
            )}
            {field.type === "number" && (
              <input
                type="number"
                value={Number(values[field.name] ?? 0)}
                onChange={(e) =>
                  setValue(field.name, parseInt(e.target.value) || 0)
                }
                className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-200 focus:border-blue-500 focus:outline-none"
              />
            )}
            {field.type === "select" && (
              <select
                value={String(values[field.name] ?? "")}
                onChange={(e) => setValue(field.name, e.target.value)}
                className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-200 focus:border-blue-500 focus:outline-none"
              >
                <option value="">Select...</option>
                {field.options?.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
            )}
            {field.type === "textarea" && (
              <textarea
                value={String(values[field.name] ?? "")}
                onChange={(e) => setValue(field.name, e.target.value)}
                placeholder={field.placeholder}
                rows={3}
                className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-200 placeholder-zinc-600 focus:border-blue-500 focus:outline-none resize-y"
              />
            )}
            {field.type === "boolean" && (
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={Boolean(values[field.name])}
                  onChange={(e) => setValue(field.name, e.target.checked)}
                  className="rounded border-zinc-600 bg-zinc-800 text-blue-500 focus:ring-blue-500"
                />
                <span className="text-xs text-zinc-400">Enabled</span>
              </label>
            )}
          </div>
        ))}
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={handleSubmit}
          disabled={!allRequiredFilled}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium text-white transition-colors",
            allRequiredFilled
              ? "bg-blue-600 hover:bg-blue-500"
              : "bg-zinc-700 cursor-not-allowed opacity-50"
          )}
        >
          <Check className="h-3 w-3" />
          Submit
        </button>
        <button
          onClick={handleReject}
          className="inline-flex items-center gap-1.5 rounded-md bg-zinc-700 px-3 py-1 text-xs font-medium text-zinc-200 hover:bg-zinc-600 transition-colors"
        >
          <X className="h-3 w-3" />
          Cancel
        </button>
      </div>
    </div>
  );
}
