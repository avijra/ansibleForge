import { useEffect, useRef } from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { TerminalSquare } from "lucide-react";

interface TerminalProps {
  sessionId: string | null;
  visible: boolean;
}

export function TerminalPanel({ sessionId, visible }: TerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<XTerm | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const fitRef = useRef<FitAddon | null>(null);

  useEffect(() => {
    if (!containerRef.current || !visible) return;

    const term = new XTerm({
      fontFamily: "'JetBrains Mono', monospace",
      fontSize: 13,
      lineHeight: 1.4,
      cursorBlink: true,
      cursorStyle: "bar",
      theme: {
        background: "#09090b",
        foreground: "#d4d4d8",
        cursor: "#a1a1aa",
        selectionBackground: "rgba(63, 63, 70, 0.5)",
        black: "#09090b",
        red: "#f87171",
        green: "#4ade80",
        yellow: "#fbbf24",
        blue: "#60a5fa",
        magenta: "#c084fc",
        cyan: "#22d3ee",
        white: "#d4d4d8",
        brightBlack: "#52525b",
        brightRed: "#fca5a5",
        brightGreen: "#86efac",
        brightYellow: "#fde68a",
        brightBlue: "#93c5fd",
        brightMagenta: "#d8b4fe",
        brightCyan: "#67e8f9",
        brightWhite: "#fafafa",
      },
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(containerRef.current);

    try {
      fitAddon.fit();
    } catch {
      // container may not be visible yet
    }

    termRef.current = term;
    fitRef.current = fitAddon;

    const ro = new ResizeObserver(() => {
      try {
        fitAddon.fit();
      } catch {
        // ignore
      }
    });
    ro.observe(containerRef.current);

    if (sessionId) {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const host = window.location.host;
      const ws = new WebSocket(`${protocol}//${host}/api/v1/terminal/${sessionId}`);

      ws.onopen = () => {
        term.writeln("\x1b[90m--- Connected to workspace terminal ---\x1b[0m\r\n");
      };

      ws.onmessage = (event) => {
        term.write(event.data);
      };

      ws.onerror = () => {
        term.writeln("\x1b[31m--- Terminal connection error ---\x1b[0m");
      };

      ws.onclose = () => {
        term.writeln("\r\n\x1b[90m--- Terminal disconnected ---\x1b[0m");
      };

      term.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(data);
        }
      });

      term.onResize(({ cols, rows }) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "resize", cols, rows }));
        }
      });

      wsRef.current = ws;
    } else {
      term.writeln("\x1b[90m--- No active session. Start a conversation to connect. ---\x1b[0m");
    }

    return () => {
      ro.disconnect();
      wsRef.current?.close();
      wsRef.current = null;
      term.dispose();
      termRef.current = null;
      fitRef.current = null;
    };
  }, [sessionId, visible]);

  if (!visible) return null;

  if (!sessionId) {
    return (
      <div className="flex items-center justify-center h-full gap-2 text-xs text-zinc-600">
        <TerminalSquare className="h-4 w-4" />
        Start a session to use the terminal
      </div>
    );
  }

  return <div ref={containerRef} className="h-full w-full" />;
}
