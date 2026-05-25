import { useCallback, useMemo, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Copy,
  Check,
  Download,
  File,
  FileCode2,
  FileText,
  FolderOpen,
  FolderClosed,
  RefreshCw,
  ScrollText,
  Settings2,
  FolderTree,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { WorkspaceFile } from "@/api/types";

interface TreeNode {
  name: string;
  path: string;
  children: Map<string, TreeNode>;
  file?: WorkspaceFile;
}

function buildTree(files: WorkspaceFile[]): TreeNode {
  const root: TreeNode = { name: "", path: "", children: new Map() };

  for (const file of files) {
    const parts = file.path.split("/");
    let current = root;

    for (let i = 0; i < parts.length - 1; i++) {
      const part = parts[i];
      if (!current.children.has(part)) {
        current.children.set(part, {
          name: part,
          path: parts.slice(0, i + 1).join("/"),
          children: new Map(),
        });
      }
      current = current.children.get(part)!;
    }

    const fileName = parts[parts.length - 1];
    current.children.set(fileName, {
      name: fileName,
      path: file.path,
      children: new Map(),
      file,
    });
  }

  return root;
}

function fileIcon(name: string) {
  const n = name.toLowerCase();
  if (n.endsWith(".yml") || n.endsWith(".yaml")) return FileCode2;
  if (n.endsWith(".tf") || n.endsWith(".tfvars") || n.endsWith(".hcl") || n.endsWith(".tfstate")) return FileCode2;
  if (n.endsWith(".j2") || n.endsWith(".jinja2")) return ScrollText;
  if (n.endsWith(".sh") || n.endsWith(".bash") || n.endsWith(".zsh")) return FileText;
  if (n.endsWith(".py") || n.endsWith(".rb") || n.endsWith(".go") || n.endsWith(".rs")) return FileCode2;
  if (n.endsWith(".js") || n.endsWith(".ts") || n.endsWith(".jsx") || n.endsWith(".tsx")) return FileCode2;
  if (n.endsWith(".cfg") || n.endsWith(".ini") || n.endsWith(".conf") || n.endsWith(".properties")) return Settings2;
  if (n.endsWith(".json") || n.endsWith(".toml") || n.endsWith(".env")) return Settings2;
  if (n.endsWith(".xml") || n.endsWith(".html") || n.endsWith(".htm")) return FileCode2;
  if (n.endsWith(".css") || n.endsWith(".scss") || n.endsWith(".less")) return FileCode2;
  if (n.endsWith(".md") || n.endsWith(".rst") || n.endsWith(".txt")) return FileText;
  if (n.endsWith(".sql")) return FileCode2;
  if (n.endsWith(".csv")) return FileText;
  if (n === "hosts" || n === "extravars" || n === "ansible.cfg") return FileText;
  if (n === "makefile" || n === "dockerfile" || n === "jenkinsfile" || n === "vagrantfile") return FileCode2;
  if (n === ".gitignore" || n === ".dockerignore" || n === ".editorconfig") return Settings2;
  if (n === "license" || n === "readme" || n === "changelog") return FileText;
  return File;
}

function fileColor(name: string): string {
  const n = name.toLowerCase();
  if (n.endsWith(".yml") || n.endsWith(".yaml")) return "text-blue-400/80";
  if (n.endsWith(".tf") || n.endsWith(".tfvars") || n.endsWith(".hcl")) return "text-purple-400/80";
  if (n.endsWith(".tfstate")) return "text-purple-300/60";
  if (n.endsWith(".j2") || n.endsWith(".jinja2")) return "text-amber-400/80";
  if (n.endsWith(".sh") || n.endsWith(".bash") || n.endsWith(".zsh")) return "text-green-400/80";
  if (n.endsWith(".py")) return "text-yellow-400/80";
  if (n.endsWith(".go")) return "text-cyan-400/80";
  if (n.endsWith(".rs")) return "text-orange-400/80";
  if (n.endsWith(".rb")) return "text-red-400/80";
  if (n.endsWith(".js") || n.endsWith(".jsx")) return "text-yellow-300/80";
  if (n.endsWith(".ts") || n.endsWith(".tsx")) return "text-blue-400/80";
  if (n.endsWith(".json")) return "text-orange-400/80";
  if (n.endsWith(".toml")) return "text-orange-300/80";
  if (n.endsWith(".xml") || n.endsWith(".html") || n.endsWith(".htm")) return "text-orange-400/80";
  if (n.endsWith(".css") || n.endsWith(".scss")) return "text-pink-400/80";
  if (n.endsWith(".md") || n.endsWith(".rst")) return "text-zinc-300/80";
  if (n.endsWith(".sql")) return "text-cyan-400/80";
  if (n.endsWith(".csv")) return "text-green-300/80";
  if (n.endsWith(".env") || n.endsWith(".properties")) return "text-yellow-500/80";
  if (n.endsWith(".cfg") || n.endsWith(".ini") || n.endsWith(".conf")) return "text-zinc-400/80";
  if (n === "hosts") return "text-teal-400/80";
  if (n === "dockerfile") return "text-sky-400/80";
  if (n === "makefile") return "text-rose-400/80";
  if (n === "jenkinsfile") return "text-red-400/80";
  if (n === "vagrantfile") return "text-blue-300/80";
  if (n.startsWith(".git") || n.startsWith(".docker") || n.startsWith(".editor")) return "text-zinc-500/80";
  if (n === "license" || n === "readme" || n === "changelog") return "text-zinc-300/80";
  return "text-zinc-500";
}

function folderColor(name: string): string {
  const n = name.toLowerCase();
  if (n === "project") return "text-blue-400/60";
  if (n === "inventory" || n === "inventories") return "text-teal-400/60";
  if (n === "env" || n === "environments") return "text-amber-400/60";
  if (n === "roles") return "text-purple-400/60";
  if (n === "templates" || n === "files") return "text-orange-400/60";
  if (n === "terraform" || n.startsWith("tf-") || n.startsWith("tf_")) return "text-purple-400/60";
  if (n === "group_vars" || n === "host_vars") return "text-teal-400/60";
  if (n === "tasks" || n === "handlers" || n === "defaults" || n === "vars" || n === "meta") return "text-blue-400/60";
  if (n === "molecule" || n === "tests" || n === "test") return "text-green-400/60";
  if (n === "playbooks") return "text-blue-400/60";
  if (n === "scripts" || n === "bin") return "text-green-400/60";
  if (n === "modules" || n === "plugins" || n === "library") return "text-amber-400/60";
  if (n === "networking" || n === "network") return "text-cyan-400/60";
  if (n === "platform" || n === "compute" || n === "app") return "text-indigo-400/60";
  if (n === "data" || n === "database" || n === "storage") return "text-rose-400/60";
  if (n === ".github" || n === ".gitlab") return "text-zinc-400/60";
  if (n === "helm" || n === "charts" || n === "manifests" || n === "k8s" || n === "kubernetes") return "text-sky-400/60";
  if (n === "ansible" || n === "ansible_collections") return "text-red-400/60";
  return "text-zinc-500";
}

function TreeFolder({
  node,
  depth,
  selectedPath,
  onSelect,
  onDoubleClick,
  defaultOpen,
}: {
  node: TreeNode;
  depth: number;
  selectedPath: string | null;
  onSelect: (file: WorkspaceFile) => void;
  onDoubleClick?: (file: WorkspaceFile) => void;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const entries = useMemo(
    () =>
      Array.from(node.children.values()).sort((a, b) => {
        const aIsDir = a.children.size > 0 && !a.file;
        const bIsDir = b.children.size > 0 && !b.file;
        if (aIsDir !== bIsDir) return aIsDir ? -1 : 1;
        return a.name.localeCompare(b.name);
      }),
    [node.children]
  );

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className={cn(
          "flex items-center gap-1.5 w-full text-left py-1 px-2 text-xs hover:bg-zinc-800/60 transition-colors rounded-sm",
        )}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        {open
          ? <ChevronDown className="h-3 w-3 text-zinc-600 shrink-0" />
          : <ChevronRight className="h-3 w-3 text-zinc-600 shrink-0" />}
        {open
          ? <FolderOpen className={cn("h-3.5 w-3.5 shrink-0", folderColor(node.name))} />
          : <FolderClosed className={cn("h-3.5 w-3.5 shrink-0", folderColor(node.name))} />}
        <span className="text-zinc-300 font-medium truncate">{node.name}</span>
        <span className="text-[10px] text-zinc-600 ml-auto shrink-0">{countFiles(node)}</span>
      </button>
      {open && (
        <div>
          {entries.map((child) =>
            child.file ? (
              <TreeFile
                key={child.path}
                node={child}
                depth={depth + 1}
                isSelected={selectedPath === child.path}
                onSelect={onSelect}
                onDoubleClick={onDoubleClick}
              />
            ) : (
              <TreeFolder
                key={child.path}
                node={child}
                depth={depth + 1}
                selectedPath={selectedPath}
                onSelect={onSelect}
                onDoubleClick={onDoubleClick}
                defaultOpen={depth < 1}
              />
            )
          )}
        </div>
      )}
    </div>
  );
}

function countFiles(node: TreeNode): number {
  let count = 0;
  for (const child of node.children.values()) {
    if (child.file) count++;
    else count += countFiles(child);
  }
  return count;
}

function TreeFile({
  node,
  depth,
  isSelected,
  onSelect,
  onDoubleClick,
}: {
  node: TreeNode;
  depth: number;
  isSelected: boolean;
  onSelect: (file: WorkspaceFile) => void;
  onDoubleClick?: (file: WorkspaceFile) => void;
}) {
  const Icon = fileIcon(node.name);
  return (
    <button
      onClick={() => node.file && onSelect(node.file)}
      onDoubleClick={() => node.file && onDoubleClick?.(node.file)}
      className={cn(
        "flex items-center gap-1.5 w-full text-left py-1 px-2 text-xs transition-colors rounded-sm",
        isSelected
          ? "bg-zinc-800 text-zinc-100"
          : "text-zinc-400 hover:bg-zinc-800/40 hover:text-zinc-300"
      )}
      style={{ paddingLeft: `${depth * 16 + 24}px` }}
    >
      <Icon className={cn("h-3.5 w-3.5 shrink-0", fileColor(node.name))} />
      <span className="truncate">{node.name}</span>
    </button>
  );
}

function FileContent({ file }: { file: WorkspaceFile }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(file.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [file.content]);

  const handleDownload = useCallback(() => {
    const blob = new Blob([file.content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = file.name;
    a.click();
    URL.revokeObjectURL(url);
  }, [file]);

  const lineCount = file.content.split("\n").length;

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-800 shrink-0">
        <span className="text-[11px] font-mono text-zinc-400 truncate flex-1">{file.path}</span>
        <span className="text-[10px] font-mono text-zinc-600 shrink-0">{lineCount} lines</span>
        <button
          onClick={handleCopy}
          className="rounded p-1 text-zinc-600 hover:bg-zinc-800 hover:text-zinc-300 transition-colors shrink-0"
          title="Copy contents"
        >
          {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
        </button>
        <button
          onClick={handleDownload}
          className="rounded p-1 text-zinc-600 hover:bg-zinc-800 hover:text-zinc-300 transition-colors shrink-0"
          title="Download file"
        >
          <Download className="h-3 w-3" />
        </button>
      </div>
      <div className="flex-1 overflow-auto">
        <pre className="p-3 text-[11px] font-mono leading-relaxed whitespace-pre">
          {highlightContent(file.name, file.content)}
        </pre>
      </div>
    </div>
  );
}

function highlightContent(filename: string, content: string): React.ReactNode {
  const n = filename.toLowerCase();
  const isYaml = n.endsWith(".yml") || n.endsWith(".yaml");
  const isJ2 = n.endsWith(".j2") || n.endsWith(".jinja2");
  const isIni = n.endsWith(".cfg") || n.endsWith(".ini") || n.endsWith(".conf") || n === "hosts" || n === "ansible.cfg";
  const isTf = n.endsWith(".tf") || n.endsWith(".tfvars") || n.endsWith(".hcl");
  const isSh = n.endsWith(".sh") || n.endsWith(".bash") || n.endsWith(".zsh") || n === "makefile";
  const isJson = n.endsWith(".json");
  const isPy = n.endsWith(".py");
  const isEnv = n.endsWith(".env") || n.endsWith(".properties");

  return content.split("\n").map((line, i) => {
    if (isYaml) return <YamlLine key={i} line={line} />;
    if (isJ2) return <Jinja2Line key={i} line={line} />;
    if (isIni || isEnv) return <IniLine key={i} line={line} />;
    if (isTf) return <HclLine key={i} line={line} />;
    if (isSh) return <ShellLine key={i} line={line} />;
    if (isJson) return <JsonLine key={i} line={line} />;
    if (isPy) return <PythonLine key={i} line={line} />;
    return <div key={i} className="text-zinc-300">{line || "\u00A0"}</div>;
  });
}

function YamlLine({ line }: { line: string }) {
  if (line.trimStart().startsWith("#")) {
    return <div className="text-zinc-600 italic">{line || "\u00A0"}</div>;
  }
  if (line.trim() === "---") {
    return <div className="text-zinc-600">{line}</div>;
  }
  if (line.includes(":") && !line.trimStart().startsWith("-")) {
    const colonIdx = line.indexOf(":");
    return (
      <div>
        <span className="text-blue-400/80">{line.slice(0, colonIdx)}</span>
        <span className="text-zinc-500">:</span>
        <span className="text-zinc-300">{line.slice(colonIdx + 1)}</span>
      </div>
    );
  }
  if (line.trimStart().startsWith("- ")) {
    return <div className="text-cyan-400/80">{line || "\u00A0"}</div>;
  }
  return <div className="text-zinc-300">{line || "\u00A0"}</div>;
}

function Jinja2Line({ line }: { line: string }) {
  if (line.trimStart().startsWith("#")) {
    return <div className="text-zinc-600 italic">{line || "\u00A0"}</div>;
  }
  const parts = line.split(/(\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\})/g);
  return (
    <div>
      {parts.map((part, j) => {
        if (part.startsWith("{{") || part.startsWith("{%") || part.startsWith("{#")) {
          return <span key={j} className="text-amber-400">{part}</span>;
        }
        return <span key={j} className="text-zinc-300">{part}</span>;
      })}
    </div>
  );
}

function IniLine({ line }: { line: string }) {
  if (line.trimStart().startsWith("#") || line.trimStart().startsWith(";")) {
    return <div className="text-zinc-600 italic">{line || "\u00A0"}</div>;
  }
  if (line.trimStart().startsWith("[")) {
    return <div className="text-teal-400 font-medium">{line || "\u00A0"}</div>;
  }
  if (line.includes("=")) {
    const eqIdx = line.indexOf("=");
    return (
      <div>
        <span className="text-blue-400/80">{line.slice(0, eqIdx)}</span>
        <span className="text-zinc-500">=</span>
        <span className="text-zinc-300">{line.slice(eqIdx + 1)}</span>
      </div>
    );
  }
  if (/^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/.test(line.trim())) {
    return <div className="text-emerald-400/80">{line || "\u00A0"}</div>;
  }
  return <div className="text-zinc-300">{line || "\u00A0"}</div>;
}

function HclLine({ line }: { line: string }) {
  const trimmed = line.trimStart();
  if (trimmed.startsWith("#") || trimmed.startsWith("//")) {
    return <div className="text-zinc-600 italic">{line || "\u00A0"}</div>;
  }
  if (/^(resource|data|variable|output|locals|module|provider|terraform)\s/.test(trimmed)) {
    const spaceIdx = trimmed.indexOf(" ");
    const lead = line.length - trimmed.length;
    return (
      <div>
        <span className="text-zinc-300">{line.slice(0, lead)}</span>
        <span className="text-purple-400 font-medium">{trimmed.slice(0, spaceIdx)}</span>
        <span className="text-zinc-300">{trimmed.slice(spaceIdx)}</span>
      </div>
    );
  }
  if (trimmed.includes("=") && !trimmed.startsWith("}")) {
    const eqIdx = line.indexOf("=");
    return (
      <div>
        <span className="text-blue-400/80">{line.slice(0, eqIdx)}</span>
        <span className="text-zinc-500">=</span>
        <span className="text-zinc-300">{line.slice(eqIdx + 1)}</span>
      </div>
    );
  }
  return <div className="text-zinc-300">{line || "\u00A0"}</div>;
}

function ShellLine({ line }: { line: string }) {
  const trimmed = line.trimStart();
  if (trimmed.startsWith("#")) {
    return <div className="text-zinc-600 italic">{line || "\u00A0"}</div>;
  }
  const parts = line.split(/(\$\{[^}]*\}|\$\w+|"[^"]*"|'[^']*')/g);
  return (
    <div>
      {parts.map((part, j) => {
        if (part.startsWith("$")) return <span key={j} className="text-cyan-400">{part}</span>;
        if (part.startsWith('"') || part.startsWith("'")) return <span key={j} className="text-green-400/80">{part}</span>;
        return <span key={j} className="text-zinc-300">{part}</span>;
      })}
    </div>
  );
}

function JsonLine({ line }: { line: string }) {
  const parts = line.split(/("(?:[^"\\]|\\.)*")/g);
  return (
    <div>
      {parts.map((part, j) => {
        if (part.startsWith('"') && (line.indexOf(part) < line.indexOf(":"))) {
          return <span key={j} className="text-blue-400/80">{part}</span>;
        }
        if (part.startsWith('"')) return <span key={j} className="text-green-400/80">{part}</span>;
        if (/true|false|null/.test(part)) return <span key={j} className="text-purple-400/80">{part}</span>;
        return <span key={j} className="text-zinc-300">{part}</span>;
      })}
    </div>
  );
}

function PythonLine({ line }: { line: string }) {
  const trimmed = line.trimStart();
  if (trimmed.startsWith("#")) {
    return <div className="text-zinc-600 italic">{line || "\u00A0"}</div>;
  }
  const kw = /^(def|class|import|from|if|elif|else|for|while|return|yield|with|as|try|except|finally|raise|pass|break|continue|and|or|not|in|is|lambda|async|await)\b/;
  if (kw.test(trimmed)) {
    const match = trimmed.match(kw)!;
    const lead = line.length - trimmed.length;
    return (
      <div>
        <span className="text-zinc-300">{line.slice(0, lead)}</span>
        <span className="text-purple-400 font-medium">{match[0]}</span>
        <span className="text-zinc-300">{trimmed.slice(match[0].length)}</span>
      </div>
    );
  }
  return <div className="text-zinc-300">{line || "\u00A0"}</div>;
}

interface WorkspaceExplorerProps {
  files: WorkspaceFile[];
  onOpenFile?: (file: WorkspaceFile) => void;
  onRefresh?: () => void;
}

export function WorkspaceExplorer({ files, onOpenFile, onRefresh }: WorkspaceExplorerProps) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null);

  const tree = useMemo(() => buildTree(files), [files]);
  const selectedFile = useMemo(
    () => files.find((f) => f.path === selectedPath) ?? null,
    [files, selectedPath]
  );

  const handleSelect = useCallback((file: WorkspaceFile) => {
    setSelectedPath(file.path);
  }, []);

  const handleDoubleClick = useCallback(
    (file: WorkspaceFile) => {
      onOpenFile?.(file);
    },
    [onOpenFile]
  );

  if (files.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 p-6 text-center">
        <div className="rounded-xl bg-zinc-900/50 p-4 ring-1 ring-zinc-800">
          <FolderTree className="h-8 w-8 text-zinc-600" />
        </div>
        <div>
          <p className="text-xs text-zinc-500">No workspace files yet</p>
          <p className="mt-1 text-[11px] text-zinc-600">
            Generated playbooks, roles, inventory, and templates will appear here
          </p>
        </div>
        {onRefresh && (
          <button
            onClick={onRefresh}
            className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs text-zinc-400 hover:text-zinc-200 bg-zinc-900 hover:bg-zinc-800 transition-colors"
          >
            <RefreshCw className="h-3 w-3" />
            Refresh
          </button>
        )}
      </div>
    );
  }

  const topEntries = Array.from(tree.children.values()).sort((a, b) => {
    const aIsDir = a.children.size > 0 && !a.file;
    const bIsDir = b.children.size > 0 && !b.file;
    if (aIsDir !== bIsDir) return aIsDir ? -1 : 1;
    return a.name.localeCompare(b.name);
  });

  return (
    <div className="flex h-full min-h-0 flex-col">
      {onRefresh && (
        <div className="flex items-center justify-between px-2 py-1.5 border-b border-zinc-800 shrink-0">
          <span className="text-[10px] text-zinc-500 uppercase tracking-wider font-medium">
            {files.length} file{files.length !== 1 ? "s" : ""}
          </span>
          <button
            onClick={onRefresh}
            className="rounded p-0.5 text-zinc-600 hover:text-zinc-400 transition-colors"
            title="Refresh files"
          >
            <RefreshCw className="h-3 w-3" />
          </button>
        </div>
      )}
      <div className="flex flex-1 min-h-0">
      {/* File tree sidebar */}
      <div className="w-[200px] shrink-0 border-r border-zinc-800 overflow-y-auto py-1">
        {topEntries.map((child) =>
          child.file ? (
            <TreeFile
              key={child.path}
              node={child}
              depth={0}
              isSelected={selectedPath === child.path}
              onSelect={handleSelect}
              onDoubleClick={handleDoubleClick}
            />
          ) : (
            <TreeFolder
              key={child.path}
              node={child}
              depth={0}
              selectedPath={selectedPath}
              onSelect={handleSelect}
              onDoubleClick={handleDoubleClick}
              defaultOpen
            />
          )
        )}
      </div>

      {/* File content pane */}
      <div className="flex-1 min-w-0 overflow-hidden">
        {selectedFile ? (
          <FileContent file={selectedFile} />
        ) : (
          <div className="flex items-center justify-center h-full text-xs text-zinc-600">
            Select a file to view its contents
          </div>
        )}
      </div>
      </div>
    </div>
  );
}
