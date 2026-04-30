import { useEffect, useRef } from "react";
import { EditorState } from "@codemirror/state";
import { EditorView, keymap, lineNumbers, highlightActiveLine, highlightSpecialChars } from "@codemirror/view";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { searchKeymap, highlightSelectionMatches } from "@codemirror/search";
import { bracketMatching, indentOnInput, syntaxHighlighting, defaultHighlightStyle, HighlightStyle } from "@codemirror/language";
import { yaml } from "@codemirror/lang-yaml";
import { json } from "@codemirror/lang-json";
import { tags } from "@lezer/highlight";

const forgeTheme = EditorView.theme({
  "&": {
    backgroundColor: "#09090b",
    color: "#d4d4d8",
    fontSize: "12px",
    fontFamily: "'JetBrains Mono', monospace",
    height: "100%",
  },
  ".cm-content": { caretColor: "#a1a1aa", padding: "8px 0" },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: "#a1a1aa" },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
    backgroundColor: "#27272a",
  },
  ".cm-activeLine": { backgroundColor: "#18181b" },
  ".cm-gutters": {
    backgroundColor: "#0a0a0b",
    color: "#52525b",
    border: "none",
    borderRight: "1px solid #1c1c1e",
  },
  ".cm-activeLineGutter": { backgroundColor: "#18181b", color: "#71717a" },
  ".cm-lineNumbers .cm-gutterElement": { padding: "0 8px 0 16px", minWidth: "32px" },
  ".cm-matchingBracket": { backgroundColor: "#3f3f46", outline: "none" },
  ".cm-searchMatch": { backgroundColor: "#854d0e40", outline: "1px solid #a16207" },
  ".cm-searchMatch.cm-searchMatch-selected": { backgroundColor: "#854d0e80" },
  ".cm-panels": { backgroundColor: "#18181b", color: "#d4d4d8" },
  ".cm-panels.cm-panels-top": { borderBottom: "1px solid #27272a" },
  ".cm-panel.cm-search": { padding: "4px 8px" },
  ".cm-panel.cm-search input": {
    backgroundColor: "#09090b",
    color: "#d4d4d8",
    border: "1px solid #3f3f46",
    borderRadius: "4px",
    padding: "2px 6px",
    fontSize: "12px",
  },
  ".cm-panel.cm-search button": {
    backgroundColor: "#27272a",
    color: "#d4d4d8",
    border: "1px solid #3f3f46",
    borderRadius: "4px",
    padding: "2px 8px",
    fontSize: "11px",
    cursor: "pointer",
  },
  ".cm-panel.cm-search label": { color: "#a1a1aa", fontSize: "11px" },
  ".cm-tooltip": { backgroundColor: "#18181b", border: "1px solid #27272a", color: "#d4d4d8" },
  ".cm-tooltip-autocomplete > ul > li": { padding: "2px 8px" },
  ".cm-tooltip-autocomplete > ul > li[aria-selected]": { backgroundColor: "#27272a" },
  ".cm-scroller": { overflow: "auto" },
}, { dark: true });

const forgeHighlight = HighlightStyle.define([
  { tag: tags.keyword, color: "#c084fc" },
  { tag: tags.string, color: "#86efac" },
  { tag: tags.comment, color: "#52525b", fontStyle: "italic" },
  { tag: tags.number, color: "#fbbf24" },
  { tag: tags.bool, color: "#f97316" },
  { tag: tags.null, color: "#f97316" },
  { tag: tags.propertyName, color: "#60a5fa" },
  { tag: tags.variableName, color: "#60a5fa" },
  { tag: tags.typeName, color: "#2dd4bf" },
  { tag: tags.operator, color: "#a1a1aa" },
  { tag: tags.punctuation, color: "#71717a" },
  { tag: tags.bracket, color: "#71717a" },
  { tag: tags.meta, color: "#71717a" },
  { tag: tags.atom, color: "#f97316" },
]);

function getLanguageExtension(lang: string) {
  switch (lang) {
    case "yaml":
    case "yml":
      return yaml();
    case "json":
      return json();
    default:
      return [];
  }
}

interface CodeEditorProps {
  content: string;
  language: string;
  onChange?: (value: string) => void;
  onSave?: (value: string) => void;
  readOnly?: boolean;
}

export function CodeEditor({ content, language, onChange, onSave, readOnly = false }: CodeEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  const onSaveRef = useRef(onSave);

  onChangeRef.current = onChange;
  onSaveRef.current = onSave;

  useEffect(() => {
    if (!containerRef.current) return;

    const saveKeymap = keymap.of([{
      key: "Mod-s",
      run: (view) => {
        onSaveRef.current?.(view.state.doc.toString());
        return true;
      },
    }]);

    const updateListener = EditorView.updateListener.of((update) => {
      if (update.docChanged) {
        onChangeRef.current?.(update.state.doc.toString());
      }
    });

    const state = EditorState.create({
      doc: content,
      extensions: [
        lineNumbers(),
        highlightActiveLine(),
        highlightSpecialChars(),
        highlightSelectionMatches(),
        history(),
        bracketMatching(),
        indentOnInput(),
        EditorState.readOnly.of(readOnly),
        saveKeymap,
        keymap.of([...defaultKeymap, ...historyKeymap, ...searchKeymap]),
        getLanguageExtension(language),
        forgeTheme,
        syntaxHighlighting(forgeHighlight),
        syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
        updateListener,
        EditorView.lineWrapping,
      ],
    });

    const view = new EditorView({ state, parent: containerRef.current });
    viewRef.current = view;

    return () => {
      view.destroy();
      viewRef.current = null;
    };
  }, [language, readOnly]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const current = view.state.doc.toString();
    if (current !== content) {
      view.dispatch({
        changes: { from: 0, to: current.length, insert: content },
      });
    }
  }, [content]);

  return <div ref={containerRef} className="h-full w-full overflow-hidden" />;
}
