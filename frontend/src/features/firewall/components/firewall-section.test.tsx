import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FirewallSection } from "@/features/firewall/components/firewall-section";
import { useFirewall } from "@/features/firewall/hooks/use-firewall";

vi.mock("@/features/firewall/hooks/use-firewall", () => ({ useFirewall: vi.fn() }));

const useFirewallMock = useFirewall as unknown as ReturnType<typeof vi.fn>;

describe("FirewallSection confirmations", () => {
  it("keeps the exact IP visible when removal fails", async () => {
    const user = userEvent.setup();
    const deleteMutation = {
      mutateAsync: vi.fn().mockRejectedValue(new Error("remove failed")),
      isPending: false,
      error: new Error("remove failed"),
    };
    useFirewallMock.mockReturnValue({
      firewallQuery: {
        data: {
          mode: "allowlist_active",
          entries: [{ ipAddress: "127.0.0.42", createdAt: "2026-03-10T12:00:00Z" }],
        },
        isLoading: false,
        error: null,
      },
      createMutation: { mutateAsync: vi.fn(), isPending: false, error: null },
      deleteMutation,
    });

    render(<FirewallSection />);
    await user.click(screen.getByRole("button", { name: "Remove" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("127.0.0.42");
    await user.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(deleteMutation.mutateAsync).toHaveBeenCalledWith("127.0.0.42"));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("127.0.0.42");
  });

  it("handles add rejection without clearing the entered IP", async () => {
    const user = userEvent.setup();
    const createMutation = {
      mutateAsync: vi.fn().mockRejectedValue(new Error("add failed")),
      isPending: false,
      error: new Error("add failed"),
    };
    useFirewallMock.mockReturnValue({
      firewallQuery: { data: { mode: "allow_all", entries: [] }, isLoading: false, error: null },
      createMutation,
      deleteMutation: { mutateAsync: vi.fn(), isPending: false, error: null },
    });

    render(<FirewallSection />);
    const input = screen.getByPlaceholderText("127.0.0.1 or 2001:db8::1");
    await user.type(input, "127.0.0.43");
    await user.click(screen.getByRole("button", { name: "Add IP" }));
    await waitFor(() => expect(createMutation.mutateAsync).toHaveBeenCalledWith("127.0.0.43"));
    expect(input).toHaveValue("127.0.0.43");
  });
});
