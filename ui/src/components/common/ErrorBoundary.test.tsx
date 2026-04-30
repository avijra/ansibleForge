import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import type { ReactNode } from "react";
import { ErrorBoundary } from "./ErrorBoundary";

function ThrowingChild(): ReactNode {
  throw new Error("Test crash");
}

describe("ErrorBoundary", () => {
  it("renders children when no error", () => {
    render(
      <ErrorBoundary>
        <p>OK</p>
      </ErrorBoundary>
    );

    expect(screen.getByText("OK")).toBeInTheDocument();
  });

  it("renders fallback when child throws", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <ErrorBoundary>
        <ThrowingChild />
      </ErrorBoundary>
    );

    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByText("Test crash")).toBeInTheDocument();
  });
});
