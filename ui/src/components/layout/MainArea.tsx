import type { ReactNode } from "react";

export function MainArea({ children }: { children: ReactNode }) {
  return (
    <main className="flex flex-1 flex-col overflow-hidden">
      {children}
    </main>
  );
}
