import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RouteErrorBoundary, RouteLoading, RouteNotFound } from "@/components/layout/route-feedback";

describe("route feedback", () => {
  afterEach(() => vi.restoreAllMocks());
  it("announces route loading instead of an empty suspense fallback", () => {
    render(<RouteLoading />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading page");
  });
  it("keeps an actionable route-render failure visible", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    function Broken(): never { throw new Error("chunk failure"); }
    render(<RouteErrorBoundary><Broken /></RouteErrorBoundary>);
    expect(screen.getByRole("alert")).toHaveTextContent("Unable to display this page");
    expect(screen.getByRole("button", { name: "Reload page" })).toBeInTheDocument();
  });
  it("provides a dashboard link for unknown routes", () => {
    render(<MemoryRouter><RouteNotFound /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to dashboard" })).toHaveAttribute("href", "/dashboard");
  });
});
