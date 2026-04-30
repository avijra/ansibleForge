import { renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useHealth } from "./useHealth";

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("useHealth", () => {
  it("returns null initially and fetches health", async () => {
    const fakeHealth = {
      status: "healthy",
      version: "0.1.0",
      llm_provider: "anthropic",
      llm_model: "anthropic/claude-sonnet-4-20250514",
      tools_available: ["generate_playbook"],
    };

    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(fakeHealth),
    } as Response);

    const { result } = renderHook(() => useHealth(60_000));

    expect(result.current.health).toBeNull();

    await waitFor(() => {
      expect(result.current.health).toEqual(fakeHealth);
    });

    expect(result.current.error).toBeNull();
  });

  it("sets error when fetch fails", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Network down"));

    const { result } = renderHook(() => useHealth(60_000));

    await waitFor(() => {
      expect(result.current.error).toBe("Network down");
    });

    expect(result.current.health).toBeNull();
  });
});
