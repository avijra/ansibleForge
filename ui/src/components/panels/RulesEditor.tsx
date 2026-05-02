import { useCallback, useEffect, useState } from "react";
import { BookOpen, Check, Save } from "lucide-react";
import { api } from "@/api/client";
import { cn } from "@/lib/utils";

interface RulesEditorProps {
  sessionId?: string;
}

export function RulesEditor({ sessionId }: RulesEditorProps) {
  const [content, setContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!sessionId) return;
    setLoading(true);
    api.rules
      .get(sessionId)
      .then((res) => {
        setContent(res.content);
        setSavedContent(res.content);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [sessionId]);

  const handleSave = useCallback(async () => {
    if (!sessionId) return;
    setSaving(true);
    try {
      await api.rules.update(sessionId, content);
      setSavedContent(content);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      /* toast later */
    } finally {
      setSaving(false);
    }
  }, [sessionId, content]);

  const hasChanges = content !== savedContent;

  if (!sessionId) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 p-6 text-center">
        <BookOpen className="h-8 w-8 text-zinc-600" />
        <p className="text-xs text-zinc-500">Open a session to edit rules</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-zinc-700 border-t-zinc-400" />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-zinc-800">
        <BookOpen className="h-3.5 w-3.5 text-zinc-500" />
        <span className="text-xs font-medium text-zinc-400">.tuyere/rules.md</span>
        <div className="ml-auto flex items-center gap-2">
          {saved && (
            <span className="flex items-center gap-1 text-[10px] text-emerald-400">
              <Check className="h-3 w-3" /> Saved
            </span>
          )}
          <button
            onClick={handleSave}
            disabled={!hasChanges || saving}
            className={cn(
              "flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-medium transition-colors",
              hasChanges
                ? "bg-zinc-700 text-zinc-200 hover:bg-zinc-600"
                : "bg-zinc-800/50 text-zinc-600 cursor-not-allowed"
            )}
          >
            <Save className="h-3 w-3" />
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        spellCheck={false}
        className="flex-1 w-full bg-transparent text-xs font-mono text-zinc-300 p-4 resize-none focus:outline-none leading-relaxed placeholder:text-zinc-700"
        placeholder="Write rules here to customize agent behavior..."
      />
    </div>
  );
}
