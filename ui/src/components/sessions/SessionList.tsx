import type { Session } from "@/api/types";
import { SessionItem } from "./SessionItem";

interface SessionListProps {
  sessions: Session[];
  activeId: string;
  onSelect: (id: string) => void;
}

export function SessionList({ sessions, activeId, onSelect }: SessionListProps) {
  return (
    <div className="space-y-0.5">
      {sessions.map((s) => (
        <SessionItem
          key={s.id}
          session={s}
          isActive={s.id === activeId}
          onClick={() => onSelect(s.id)}
        />
      ))}
    </div>
  );
}
