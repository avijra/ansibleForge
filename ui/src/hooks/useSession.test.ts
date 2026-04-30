import { renderHook, act } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { useSession } from "./useSession";

describe("useSession", () => {
  it("starts with one active session", () => {
    const { result } = renderHook(() => useSession());

    expect(result.current.sessions).toHaveLength(1);
    expect(result.current.active.id).toMatch(/^local-/);
    expect(result.current.active.events).toEqual([]);
  });

  it("creates a new session", () => {
    const { result } = renderHook(() => useSession());

    act(() => {
      result.current.newSession();
    });

    expect(result.current.sessions).toHaveLength(2);
  });

  it("adds events to a session", () => {
    const { result } = renderHook(() => useSession());
    const id = result.current.active.id;

    act(() => {
      result.current.addEvent(id, {
        id: "evt-1",
        event: "user_message",
        data: { content: "hello" },
        timestamp: Date.now(),
      });
    });

    expect(result.current.active.events).toHaveLength(1);
    expect(result.current.active.title).toBe("hello");
  });

  it("deletes a session and creates a fresh one if empty", () => {
    const { result } = renderHook(() => useSession());
    const id = result.current.active.id;

    act(() => {
      result.current.deleteSession(id);
    });

    expect(result.current.sessions).toHaveLength(1);
    expect(result.current.active.id).not.toBe(id);
  });

  it("updates session id", () => {
    const { result } = renderHook(() => useSession());
    const oldId = result.current.active.id;

    act(() => {
      result.current.updateSessionId(oldId, "server-abc123");
    });

    expect(result.current.active.id).toBe("server-abc123");
    expect(result.current.activeId).toBe("server-abc123");
  });
});
