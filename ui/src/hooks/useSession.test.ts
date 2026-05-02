import { renderHook, act } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { useSession } from "./useSession";

describe("useSession", () => {
  it("starts with no active session when localStorage is empty", () => {
    const { result } = renderHook(() => useSession());

    expect(result.current.sessions).toHaveLength(0);
    expect(result.current.active).toBeUndefined();
    expect(result.current.activeId).toBeNull();
  });

  it("creates a new session with a project path", () => {
    const { result } = renderHook(() => useSession());

    act(() => {
      result.current.newSession("/tmp/my-project");
    });

    expect(result.current.sessions).toHaveLength(1);
    expect(result.current.active).toBeDefined();
    expect(result.current.active!.projectPath).toBe("/tmp/my-project");
    expect(result.current.active!.id).toMatch(/^local-/);
  });

  it("adds events to a session", () => {
    const { result } = renderHook(() => useSession());

    act(() => {
      result.current.newSession("/tmp/test");
    });

    const id = result.current.active!.id;

    act(() => {
      result.current.addEvent(id, {
        id: "evt-1",
        event: "user_message",
        data: { content: "hello" },
        timestamp: Date.now(),
      });
    });

    expect(result.current.active!.events).toHaveLength(1);
    expect(result.current.active!.title).toBe("hello");
  });

  it("deletes a session and goes to empty state when last one removed", () => {
    const { result } = renderHook(() => useSession());

    act(() => {
      result.current.newSession("/tmp/test");
    });

    const id = result.current.active!.id;

    act(() => {
      result.current.deleteSession(id);
    });

    expect(result.current.sessions).toHaveLength(0);
    expect(result.current.active).toBeUndefined();
    expect(result.current.activeId).toBeNull();
  });

  it("updates session id", () => {
    const { result } = renderHook(() => useSession());

    act(() => {
      result.current.newSession("/tmp/test");
    });

    const oldId = result.current.active!.id;

    act(() => {
      result.current.updateSessionId(oldId, "server-abc123");
    });

    expect(result.current.active!.id).toBe("server-abc123");
    expect(result.current.activeId).toBe("server-abc123");
  });

  it("restores a remote session by id", () => {
    const { result } = renderHook(() => useSession());

    act(() => {
      result.current.restoreRemoteSession("srv-123", "/tmp/infra", "deploy nginx");
    });

    expect(result.current.sessions).toHaveLength(1);
    expect(result.current.active).toBeDefined();
    expect(result.current.active!.id).toBe("srv-123");
    expect(result.current.active!.projectPath).toBe("/tmp/infra");
    expect(result.current.active!.title).toBe("deploy nginx");
  });

  it("clears all sessions to empty state", () => {
    const { result } = renderHook(() => useSession());

    act(() => {
      result.current.newSession("/tmp/a");
      result.current.newSession("/tmp/b");
    });

    expect(result.current.sessions).toHaveLength(2);

    act(() => {
      result.current.clearAllSessions();
    });

    expect(result.current.sessions).toHaveLength(0);
    expect(result.current.active).toBeUndefined();
  });
});
