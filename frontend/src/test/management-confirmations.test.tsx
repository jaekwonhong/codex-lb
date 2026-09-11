import { Suspense } from "react";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { AccountsPage } from "@/features/accounts/components/accounts-page";
import { ApisPage } from "@/features/apis/components/apis-page";
import { ApiKeysSection } from "@/features/api-keys/components/api-keys-section";
import { useAuthStore } from "@/features/auth/hooks/use-auth";
import { createAccountSummary } from "@/test/mocks/factories";
import { installMemberSwitchMocks } from "@/test/mocks/member-switch";
import { server } from "@/test/mocks/server";
import { renderWithProviders } from "@/test/utils";

const target = createAccountSummary({ displayName: "Review target", availableResetCredits: 2 });
const failed = () => HttpResponse.json({ error: { code: "synthetic_rejected", message: "Synthetic action failed" } }, { status: 503 });

beforeEach(() => {
  useAuthStore.setState({ canWrite: true });
  localStorage.clear(); sessionStorage.clear();
  installMemberSwitchMocks();
  server.use(http.get("/api/accounts", () => HttpResponse.json({ accounts: [target] })));
});

async function accountDialog(action: "Delete" | "Reset usage" = "Delete") {
  const user = userEvent.setup();
  const view = renderWithProviders(<AccountsPage />);
  await user.click(await screen.findByRole("button", { name: action }));
  const dialog = await screen.findByRole("alertdialog");
  return { ...view, user, dialog };
}

describe("account confirmation intent", () => {
  it("shows the exact target and cancels without changing it", async () => {
    let writes = 0;
    server.use(http.delete("/api/accounts/:id", () => { writes++; return failed(); }));
    const { user, dialog } = await accountDialog();
    expect(dialog).toHaveTextContent(target.email);
    expect(dialog).toHaveTextContent(target.accountId);
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(writes).toBe(0);
  });

  it("keeps a pending delete visible and its scope immutable", async () => {
    let release!: () => void;
    const wait = new Promise<void>((resolve) => { release = resolve; });
    let writes = 0;
    server.use(http.delete("/api/accounts/:id", async () => { writes++; await wait; return HttpResponse.json({ status: "deleted" }); }));
    const { user, dialog } = await accountDialog();
    await user.click(within(dialog).getByRole("checkbox"));
    try {
      await user.click(within(dialog).getByRole("button", { name: "Delete" }));
      await waitFor(() => expect(writes).toBe(1));
      expect(screen.getByRole("alertdialog")).toBeVisible();
      expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeDisabled();
      expect(within(dialog).getByRole("checkbox")).toBeDisabled();
    } finally { await act(async () => { release(); }); }
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(writes).toBe(1);
  });

  it("preserves a failed delete target, scope and error without another request", async () => {
    const urls: string[] = [];
    server.use(http.delete("/api/accounts/:id", ({ request }) => { urls.push(request.url); return failed(); }));
    const { user, dialog } = await accountDialog();
    await user.click(within(dialog).getByRole("checkbox"));
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(within(screen.getByRole("alertdialog")).getByRole("alert")).toHaveTextContent("Synthetic action failed"));
    expect(within(dialog).getByRole("checkbox")).toBeChecked();
    expect(dialog).toHaveTextContent(target.accountId);
    expect(urls).toHaveLength(1);
    expect(new URL(urls[0]).searchParams.get("delete_history")).toBe("true");
  });

  it.each(["permission", "missing target", "list failure"])("blocks an open confirmation after %s changes", async (reason) => {
    let writes = 0;
    server.use(http.delete("/api/accounts/:id", () => { writes++; return failed(); }));
    const { user, dialog, queryClient } = await accountDialog();
    await act(async () => {
      if (reason === "permission") useAuthStore.setState({ canWrite: false });
      else if (reason === "missing target") queryClient.setQueryData(["accounts", "list"], { accounts: [createAccountSummary({ accountId: "other", email: "other@example.com" })] });
      else {
        server.use(http.get("/api/accounts", failed));
        await queryClient.refetchQueries({ queryKey: ["accounts", "list"] });
      }
    });
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Delete" })).toBeDisabled());
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(writes).toBe(0);
  });

  it("retains a failed usage reset and reuses the redemption identity on explicit retry", async () => {
    const bodies: unknown[] = [];
    server.use(http.post("/api/accounts/:id/usage-reset-credits/consume", async ({ request }) => { bodies.push(await request.json()); return failed(); }));
    const { user, dialog } = await accountDialog("Reset usage");
    await user.click(within(dialog).getByRole("button", { name: "Reset" }));
    await waitFor(() => expect(within(screen.getByRole("alertdialog")).getByRole("alert")).toHaveTextContent("Synthetic action failed"));
    expect(dialog).toHaveTextContent(target.accountId);
    await user.click(within(dialog).getByRole("button", { name: "Reset" }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[0]).toEqual(bodies[1]);
  });
});

describe("API-key confirmation consumers", () => {
  it.each(["page", "section"])("keeps %s deletion visible after failure", async (surface) => {
    let writes = 0;
    server.use(http.delete("/api/api-keys/:id", () => { writes++; return failed(); }));
    const user = userEvent.setup();
    renderWithProviders(<Suspense fallback={null}>{surface === "page" ? <ApisPage /> : <ApiKeysSection apiKeyAuthEnabled hideUpstreamQuotaFromApiKeys={false} onApiKeyAuthEnabledChange={() => {}} onHideUpstreamQuotaFromApiKeysChange={() => {}} />}</Suspense>);
    if (surface === "section") await user.click((await screen.findAllByRole("button", { name: "Actions" }))[0]);
    await user.click(await screen.findByRole(surface === "section" ? "menuitem" : "button", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(within(screen.getByRole("alertdialog")).getByRole("alert")).toHaveTextContent("Synthetic action failed"));
    expect(dialog).toHaveTextContent("Default key");
    expect(dialog).toHaveTextContent("key_1");
    expect(writes).toBe(1);
  });

  it("keeps API browsing available without exposing enabled write controls to read-only users", async () => {
    useAuthStore.setState({ canWrite: false });
    renderWithProviders(<ApisPage />);
    expect(await screen.findByRole("button", { name: "Create API Key" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
    expect(screen.getByRole("heading", { name: "Default key" })).toBeVisible();
  });
});
