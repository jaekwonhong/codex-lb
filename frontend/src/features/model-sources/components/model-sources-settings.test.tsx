import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ModelSourcesSettings } from "@/features/model-sources/components/model-sources-settings";
import { useModelSources } from "@/features/model-sources/hooks/use-model-sources";
import { createModelSource } from "@/test/mocks/factories";

vi.mock("@/features/model-sources/hooks/use-model-sources", () => ({ useModelSources: vi.fn() }));

const useModelSourcesMock = useModelSources as unknown as ReturnType<typeof vi.fn>;

describe("ModelSourcesSettings destructive actions", () => {
  it("preserves the exact source confirmation when deletion fails", async () => {
    const user = userEvent.setup();
    const source = createModelSource({ id: "source_exact", name: "Exact Source" });
    const deleteMutation = {
      mutateAsync: vi.fn().mockRejectedValue(new Error("delete failed")),
      isPending: false,
      error: new Error("delete failed"),
    };
    useModelSourcesMock.mockReturnValue({
      modelSourcesQuery: { data: { sources: [source] }, isFetching: false, error: null },
      createMutation: { mutateAsync: vi.fn(), isPending: false, error: null },
      updateMutation: { mutateAsync: vi.fn(), isPending: false, error: null },
      deleteMutation,
    });

    render(<ModelSourcesSettings />);
    await user.click(screen.getByRole("button", { name: "Delete Exact Source model source" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Exact Source");
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleteMutation.mutateAsync).toHaveBeenCalledWith("source_exact"));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Exact Source");
  });

  it("handles a failed enable toggle without an unhandled rejection", async () => {
    const user = userEvent.setup();
    const source = createModelSource({ id: "source_toggle", name: "Toggle Source", isEnabled: true });
    const updateMutation = {
      mutateAsync: vi.fn().mockRejectedValue(new Error("update failed")),
      isPending: false,
      error: new Error("update failed"),
    };
    useModelSourcesMock.mockReturnValue({
      modelSourcesQuery: { data: { sources: [source] }, isFetching: false, error: null },
      createMutation: { mutateAsync: vi.fn(), isPending: false, error: null },
      updateMutation,
      deleteMutation: { mutateAsync: vi.fn(), isPending: false, error: null },
    });

    render(<ModelSourcesSettings />);
    await user.click(screen.getByRole("switch", { name: "Toggle Toggle Source model source" }));
    await waitFor(() => {
      expect(updateMutation.mutateAsync).toHaveBeenCalledWith({
        sourceId: "source_toggle",
        payload: { isEnabled: false },
      });
    });
    expect(screen.getByText("Toggle Source")).toBeInTheDocument();
  });
});
