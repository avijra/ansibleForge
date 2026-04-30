import { useEffect, useRef } from "react";

interface ShortcutDef {
  handler: () => void;
  description: string;
}

type ShortcutMap = Record<string, ShortcutDef>;

function normalizeEvent(e: KeyboardEvent): string {
  const parts: string[] = [];
  if (e.metaKey || e.ctrlKey) parts.push("meta");
  if (e.shiftKey) parts.push("shift");
  if (e.altKey) parts.push("alt");

  let key = e.key.toLowerCase();
  if (key === " ") key = "space";
  if (key === "escape") key = "escape";

  if (!["meta", "shift", "alt", "control"].includes(key)) {
    parts.push(key);
  }

  return parts.join("+");
}

export function useKeyboard(shortcuts: ShortcutMap): ShortcutMap {
  const shortcutsRef = useRef(shortcuts);
  shortcutsRef.current = shortcuts;

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      const isInput = target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable;

      const combo = normalizeEvent(e);
      const def = shortcutsRef.current[combo];
      if (!def) return;

      if (combo === "escape" || !isInput) {
        e.preventDefault();
        e.stopPropagation();
        def.handler();
      }
    }

    document.addEventListener("keydown", handleKeyDown, true);
    return () => document.removeEventListener("keydown", handleKeyDown, true);
  }, []);

  return shortcuts;
}
