import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type PropsWithChildren } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "@/features/settings/api";
import { useSettings } from "./use-settings";
import { buildSettingsUpdateRequest } from "@/features/settings/payload";
import { DashboardSettingsSchema } from "@/features/settings/schemas";
import { createDashboardSettings } from "@/test/mocks/factories";

afterEach(() => vi.restoreAllMocks());

function snapshot(overrides: Parameters<typeof createDashboardSettings>[0]) {
  return DashboardSettingsSchema.parse(createDashboardSettings(overrides));
}

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const wrapper = ({ children }: PropsWithChildren) => createElement(QueryClientProvider, { client }, children);
  return { client, ...renderHook(() => useSettings(), { wrapper }) };
}

describe("settings save snapshot", () => {
  it("does not replace a newer confirmed cache entry with a delayed PUT response", async () => {
    const old = snapshot({ version: 30, importWithoutOverwrite: false });
    const saved = snapshot({ ...old, version: 31, importWithoutOverwrite: true });
    const newer = snapshot({ ...saved, version: 32, showResetCreditBadges: false });
    vi.spyOn(api, "getSettings").mockResolvedValueOnce(old).mockRejectedValue(new Error("Read unavailable"));
    const hook = setup();
    vi.spyOn(api, "updateSettings").mockImplementation(async () => {
      // Another completed GET may already have observed a later server version.
      hook.client.setQueryData(["settings", "detail"], newer);
      return saved;
    });
    try {
      await waitFor(() => expect(hook.result.current.settingsQuery.data?.version).toBe(30));
      await act(() => hook.result.current.updateSettingsMutation.mutateAsync({ expectedVersion: 30, importWithoutOverwrite: true }));
      await waitFor(() => expect(hook.result.current.settingsQuery.error?.message).toBe("Read unavailable"));
      expect(hook.result.current.settingsQuery.data).toEqual(newer);
    } finally { hook.unmount(); hook.client.clear(); }
  });

  it("retains the confirmed PUT response when follow-up GET fails", async () => {
    const old = snapshot({ version: 10, importWithoutOverwrite: false });
    const saved = snapshot({ ...old, version: 11, importWithoutOverwrite: true });
    vi.spyOn(api, "getSettings").mockResolvedValueOnce(old).mockRejectedValue(new Error("Read unavailable"));
    const update = vi.spyOn(api, "updateSettings").mockResolvedValue(saved);
    const hook = setup();
    try {
      await waitFor(() => expect(hook.result.current.settingsQuery.data?.version).toBe(10));
      await act(() => hook.result.current.updateSettingsMutation.mutateAsync(
        buildSettingsUpdateRequest(old, { importWithoutOverwrite: true }),
      ));
      await waitFor(() => expect(hook.result.current.settingsQuery.error?.message).toBe("Read unavailable"));
      expect(hook.result.current.settingsQuery.data).toEqual(saved);
      expect(buildSettingsUpdateRequest(hook.result.current.settingsQuery.data!, {}).expectedVersion).toBe(11);
      expect(update).toHaveBeenCalledTimes(1);
    } finally { hook.unmount(); hook.client.clear(); }
  });

  it("uses the confirmed version before a slow follow-up read completes", async () => {
    const old = snapshot({ version: 20 });
    const saved = snapshot({ ...old, version: 21, importWithoutOverwrite: true });
    const next = snapshot({ ...saved, version: 22, showResetCreditBadges: false });
    let resolveRead!: (value: typeof old) => void;
    const pendingRead = new Promise<typeof old>((resolve) => { resolveRead = resolve; });
    vi.spyOn(api, "getSettings").mockResolvedValueOnce(old).mockReturnValue(pendingRead);
    const update = vi.spyOn(api, "updateSettings").mockResolvedValueOnce(saved).mockResolvedValueOnce(next);
    const hook = setup();
    try {
      await waitFor(() => expect(hook.result.current.settingsQuery.data?.version).toBe(20));
      await act(() => hook.result.current.updateSettingsMutation.mutateAsync(
        buildSettingsUpdateRequest(old, { importWithoutOverwrite: true }),
      ));
      expect(hook.result.current.updateSettingsMutation.isPending).toBe(false);
      await waitFor(() => expect(hook.result.current.settingsQuery.data).toEqual(saved));
      await act(() => hook.result.current.updateSettingsMutation.mutateAsync(
        buildSettingsUpdateRequest(hook.result.current.settingsQuery.data!, { showResetCreditBadges: false }),
      ));
      expect(update.mock.calls[1][0]).toMatchObject({ expectedVersion: 21, importWithoutOverwrite: true });
      resolveRead(next);
      await waitFor(() => expect(hook.result.current.settingsQuery.isFetching).toBe(false));
      expect(hook.result.current.settingsQuery.data).toEqual(next);
    } finally { resolveRead(next); hook.unmount(); hook.client.clear(); }
  });
});
