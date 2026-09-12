import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useMemberSwitch } from "./use-member-switch";
import { installMemberSwitchMocks, makeAuthEnrollmentView, makeRunView, memberIdentity } from "@/test/mocks/member-switch";
import { readAuthEnrollmentLocator, readRunLocator } from "@/features/member-switch/active-flow";

describe("server-owned member switch", () => {
  let mock: ReturnType<typeof installMemberSwitchMocks>;
  beforeEach(() => { localStorage.clear(); sessionStorage.clear(); mock = installMemberSwitchMocks(); });
  async function mount(onAuthEnrollmentSettled?: (accountId: string | null) => void) {
    const hook = renderHook(() => useMemberSwitch(false, onAuthEnrollmentSettled));
    await waitFor(() => expect(hook.result.current.checked).toBe(true));
    return hook;
  }
  async function preview(hook: Awaited<ReturnType<typeof mount>>) {
    await act(hook.result.current.loadCatalog);
    await act(() => hook.result.current.preview("cdp-1", "cdp-1-target"));
  }
  it("restores from the server without browser storage and never mutates on lifecycle events", async () => {
    mock.run = makeRunView({ phase: "membership_requested", operationId: "operation-1", allowedActions: ["observe_membership"] });
    const hook = await mount();
    expect(hook.result.current.flow?.id).toBe(mock.run.id);
    await act(async () => { window.dispatchEvent(new Event("focus")); window.dispatchEvent(new Event("online")); });
    expect(mock.requests.map((item) => item.method)).toEqual(["GET", "GET"]);
    expect(readRunLocator()).toBe(mock.run.id);
  });
  it("does not request anything as a read-only caller", async () => {
    const hook = renderHook(() => useMemberSwitch(true));
    await act(hook.result.current.loadCatalog);
    await act(hook.result.current.refresh);
    expect(mock.requests).toEqual([]);
  });
  it("sends one run command and no direct Companion traffic", async () => {
    const hook = await mount(); await preview(hook);
    await act(async () => { await Promise.all([hook.result.current.command("start"), hook.result.current.command("start")]); });
    const commands = mock.requests.filter((item) => item.path.endsWith("/commands"));
    expect(commands).toHaveLength(1);
    expect(commands[0].body).toMatchObject({ action: "start", expectedRevision: 2 });
    expect(mock.requests.every((item) => item.path.startsWith("/api/member-switch-runs"))).toBe(true);
  });
  it("does not refresh live membership while an unfinished run is active", async () => {
    mock.run = makeRunView({ phase: "membership_requested", operationId: "operation-1", allowedActions: ["observe_membership"] });
    const hook = await mount();
    await act(hook.result.current.loadCatalog);
    expect(mock.requests.filter((item) => item.path.endsWith("/catalog/refresh"))).toEqual([]);
  });
  it("shows the confirmed operation member immediately without a mid-run catalog refresh", async () => {
    const hook = await mount(); await preview(hook);
    await act(() => hook.result.current.command("start"));
    await act(() => hook.result.current.command("observe_membership"));
    expect(hook.result.current.catalog?.workspaces[0].currentMembers).toEqual([
      { email: memberIdentity.targetEmail, userId: memberIdentity.targetUserId,
        presetId: memberIdentity.presetId, authState: "unknown", authAccountId: null },
    ]);
    expect(hook.result.current.catalog?.workspaces[0].membershipCode).toBe("confirmed_by_operation");
    expect(mock.requests.filter((item) => item.path.endsWith("/catalog/refresh"))).toHaveLength(1);
  });
  it("finishing a preflight failure does not auto-reclaim the owner browser via catalog", async () => {
    mock.run = makeRunView({phase: "needs_attention", lastCode: "ego_owner_profile_login_required",
      operationId: "operation-1", allowedActions: ["observe_membership", "finish"]});
    const hook = await mount();
    await act(() => hook.result.current.command("finish"));
    expect(hook.result.current.flow?.phase).toBe("completed");
    expect(mock.requests.filter(item => item.path.endsWith("/catalog/refresh"))).toHaveLength(0);
    expect(hook.result.current.catalog).toBeNull();
    await act(hook.result.current.loadCatalog);
    expect(mock.requests.filter(item => item.path.endsWith("/catalog/refresh"))).toHaveLength(1);
    expect(mock.requests.filter(item => item.path.endsWith("/commands"))).toHaveLength(1);
  });
  it("refreshes actual membership once after a successful finish", async () => {
    mock.run = makeRunView({
      phase: "auth_confirmed", operationId: "operation-1", authState: "completed", allowedActions: ["finish"],
    });
    const hook = await mount();
    await act(() => hook.result.current.command("finish"));
    expect(hook.result.current.flow?.phase).toBe("completed");
    expect(mock.requests.filter((item) => item.path.endsWith("/commands"))).toHaveLength(1);
    expect(mock.requests.filter((item) => item.path.endsWith("/catalog/refresh"))).toHaveLength(1);
  });
  it("lost response blocks another command until a stored-state refresh, then explicit reconciliation", async () => {
    const hook = await mount(); await preview(hook); mock.loseResponseFor = "start";
    await act(() => hook.result.current.command("start"));
    expect(hook.result.current.checked).toBe(false);
    await act(() => hook.result.current.command("start"));
    expect(mock.requests.filter((item) => item.path.endsWith("/commands"))).toHaveLength(1);
    await act(hook.result.current.refresh);
    expect(hook.result.current.flow?.phase).toBe("outcome_unknown");
    await act(() => hook.result.current.command("reconcile"));
    expect(hook.result.current.flow?.phase).toBe("membership_requested");
  });
  it("a lost create response is recovered even after all browser storage is erased", async () => {
    const hook = await mount(); mock.loseResponseFor = "create"; await preview(hook);
    const id = readRunLocator(); expect(id).toBe(mock.run?.id);
    hook.unmount(); localStorage.clear();
    const restored = await mount();
    expect(restored.result.current.flow?.id).toBe(id);
    expect(mock.requests.filter((item) => item.path === "/api/member-switch-runs")).toHaveLength(1);
  });
  it("does not advance auth through the stored status button", async () => {
    mock.run = makeRunView({ phase: "auth_prepared", handoffId: "auth-1", authState: "oauth_pending", allowedActions: ["observe_auth", "advance_auth"] });
    const hook = await mount(); await act(() => hook.result.current.command("observe_auth"));
    expect(hook.result.current.flow?.authState).toBe("oauth_pending");
    expect(mock.requests.filter((item) => item.method === "POST").map((item) => item.body)).toEqual([
      expect.objectContaining({ action: "observe_auth" }),
    ]);
  });
  it("a stale revision conflicts rather than starting another operation", async () => {
    const hook = await mount(); await preview(hook);
    mock.run = { ...mock.run!, revision: 10 };
    await act(() => hook.result.current.command("start"));
    expect(hook.result.current.error).toBe("revision_conflict");
    expect(mock.run.phase).toBe("previewed");
    await act(hook.result.current.refresh); expect(hook.result.current.flow?.revision).toBe(10);
  });
  it("completes OAuth enrollment from one click and dismisses the completed record", async () => {
    const onAuthEnrollmentSettled = vi.fn();
    mock.catalog.workspaces[0].currentMembers = [{
      email: memberIdentity.targetEmail,
      userId: memberIdentity.targetUserId,
      presetId: memberIdentity.presetId,
      authState: "absent",
      authAccountId: null,
    }];
    const hook = await mount(onAuthEnrollmentSettled);
    await act(hook.result.current.loadCatalog);
    await act(() => hook.result.current.startAuthEnrollment(
      "cdp-1", memberIdentity.presetId, memberIdentity.targetEmail, memberIdentity.targetUserId,
    ));

    expect(hook.result.current.enrollment).toBeNull();
    expect(hook.result.current.flow).toBeNull();
    expect(hook.result.current.catalog?.workspaces[0].currentMembers[0]?.authState).toBe("active");
    expect(hook.result.current.catalog?.workspaces[0].currentMembers[0]?.authAccountId).toBe("auth-target");
    expect(hook.result.current.oauthProbe?.probeStatusCode).toBe(200);
    expect(hook.result.current.oauthProbe?.accountId).toBe("auth-target");
    expect(hook.result.current.oauthProbe?.state).toBe("completed");
    expect(onAuthEnrollmentSettled).toHaveBeenCalledTimes(1);
    expect(onAuthEnrollmentSettled).toHaveBeenCalledWith("auth-target");
    expect(mock.requests.filter((item) => item.path === "/api/member-switch-runs/oauth-enrollments/auto")).toHaveLength(1);
    expect(mock.requests.filter((item) => item.path === "/api/accounts/auth-target/probe")).toHaveLength(0);
    expect(mock.requests.filter((item) => item.path.includes("/oauth-enrollments/") && item.path.endsWith("/commands"))).toHaveLength(0);
  });

  it("auto-recovers a terminal OAuth response whose server post-probe is still pending", async () => {
    mock.omitInitialPostProbeOnce = true;
    mock.catalog.workspaces[0].currentMembers = [{
      email: memberIdentity.targetEmail,
      userId: memberIdentity.targetUserId,
      presetId: memberIdentity.presetId,
      authState: "absent",
      authAccountId: null,
    }];
    const hook = await mount();
    await act(hook.result.current.loadCatalog);

    await act(() => hook.result.current.startAuthEnrollment(
      "cdp-1", memberIdentity.presetId, memberIdentity.targetEmail, memberIdentity.targetUserId,
    ));

    expect(hook.result.current.checked).toBe(true);
    expect(hook.result.current.enrollment).toBeNull();
    expect(hook.result.current.oauthProbe?.state).toBe("completed");
    expect(hook.result.current.oauthProbe?.accountId).toBe("auth-target");
    expect(mock.requests.filter((item) => item.path === "/api/member-switch-runs/oauth-enrollments/auto")).toHaveLength(1);
    expect(mock.requests.filter((item) => /\/oauth-enrollments\/[^/]+\/auto$/.test(item.path))).toHaveLength(1);
    expect(mock.requests.filter((item) => item.path === "/api/accounts/auth-target/probe")).toHaveLength(0);
    expect(readAuthEnrollmentLocator()).toBeNull();
  });

  it("observes persisted OAuth progress without replaying enrollment effects", async () => {
    mock.autoEnrollmentDelayMs = 700;
    mock.catalog.workspaces[0].currentMembers = [{
      email: memberIdentity.targetEmail,
      userId: memberIdentity.targetUserId,
      presetId: memberIdentity.presetId,
      authState: "absent",
      authAccountId: null,
    }];
    const hook = await mount();
    await act(hook.result.current.loadCatalog);
    let pending!: Promise<void>;
    act(() => {
      pending = hook.result.current.startAuthEnrollment(
        "cdp-1", memberIdentity.presetId, memberIdentity.targetEmail, memberIdentity.targetUserId,
      );
    });

    await waitFor(() => expect(hook.result.current.autoProgress?.phase).toBe("auth_prepared"), { timeout: 2_000 });
    expect(mock.requests.filter((item) => item.method === "GET" && /\/oauth-enrollments\/[^/]+$/.test(item.path)).length).toBeGreaterThan(0);
    expect(mock.requests.filter((item) => item.path.includes("/oauth-enrollments/") && item.path.endsWith("/commands"))).toHaveLength(0);

    await act(async () => { await pending; });
    expect(hook.result.current.autoProgress).toBeNull();
    expect(mock.requests.filter((item) => item.path === "/api/member-switch-runs/oauth-enrollments/auto")).toHaveLength(1);
    expect(mock.requests.filter((item) => item.path === "/api/accounts/auth-target/probe")).toHaveLength(0);
  });

  it("keeps OAuth success when the post-registration Force Probe fails", async () => {
    mock.probeErrorCode = "account_probe_refresh_failed";
    mock.catalog.workspaces[0].currentMembers = [{
      email: memberIdentity.targetEmail,
      userId: memberIdentity.targetUserId,
      presetId: memberIdentity.presetId,
      authState: "absent",
      authAccountId: null,
    }];
    const hook = await mount();
    await act(hook.result.current.loadCatalog);
    await act(() => hook.result.current.startAuthEnrollment(
      "cdp-1", memberIdentity.presetId, memberIdentity.targetEmail, memberIdentity.targetUserId,
    ));

    expect(hook.result.current.enrollment).toBeNull();
    expect(hook.result.current.catalog?.workspaces[0].currentMembers[0]?.authState).toBe("active");
    expect(hook.result.current.error).toBeNull();
    expect(hook.result.current.oauthProbe?.errorCode).toBe("account_probe_refresh_failed");
    expect(mock.requests.filter((item) => item.path === "/api/accounts/auth-target/probe")).toHaveLength(0);
  });

  it("recovers a lost successful one-click reply without replaying enrollment", async () => {
    mock.loseAutoEnrollmentResponse = true;
    mock.catalog.workspaces[0].currentMembers = [{
      email: memberIdentity.targetEmail,
      userId: memberIdentity.targetUserId,
      presetId: memberIdentity.presetId,
      authState: "absent",
      authAccountId: null,
    }];
    const hook = await mount();
    await act(hook.result.current.loadCatalog);
    await act(() => hook.result.current.startAuthEnrollment(
      "cdp-1", memberIdentity.presetId, memberIdentity.targetEmail, memberIdentity.targetUserId,
    ));
    expect(hook.result.current.checked).toBe(false);
    expect(mock.requests.filter((item) => item.path === "/api/member-switch-runs/oauth-enrollments/auto")).toHaveLength(1);

    // Simulate a process stop after terminal OAuth closeout but before the server
    // persisted its post-probe diagnostic. Refresh may read the terminal row, but
    // only the server-owned auto endpoint may perform the missing Probe effect.
    mock.enrollment = mock.enrollment ? { ...mock.enrollment, postProbe: null } : null;
    mock.loseAutoEnrollmentResponse = false;
    await act(hook.result.current.refresh);

    expect(hook.result.current.enrollment).toBeNull();
    expect(hook.result.current.catalog).toBeNull();
    expect(hook.result.current.oauthProbe?.accountId).toBe("auth-target");
    expect(hook.result.current.oauthProbe?.state).toBe("completed");
    expect(mock.requests.filter((item) => item.path === "/api/member-switch-runs/oauth-enrollments/auto")).toHaveLength(1);
    expect(mock.requests.filter((item) => /\/oauth-enrollments\/[^/]+\/auto$/.test(item.path))).toHaveLength(1);
    expect(mock.requests.filter((item) => item.path.includes("/oauth-enrollments/") && item.path.endsWith("/commands"))).toHaveLength(0);
    expect(mock.requests.filter((item) => item.path === "/api/accounts/auth-target/probe")).toHaveLength(0);
    expect(readAuthEnrollmentLocator()).toBeNull();
  });

  it("rejects a reentrant OAuth start without replacing the owning locator or progress", async () => {
    mock.autoEnrollmentDelayMs = 300;
    mock.loseAutoEnrollmentResponse = true;
    mock.catalog.workspaces[0].currentMembers = [{
      email: memberIdentity.targetEmail,
      userId: memberIdentity.targetUserId,
      presetId: memberIdentity.presetId,
      authState: "absent",
      authAccountId: null,
    }];
    const hook = await mount();
    await act(hook.result.current.loadCatalog);
    let first!: Promise<void>;
    let second!: Promise<void>;
    act(() => {
      first = hook.result.current.startAuthEnrollment(
        "cdp-1", memberIdentity.presetId, memberIdentity.targetEmail, memberIdentity.targetUserId,
      );
      second = hook.result.current.startAuthEnrollment(
        "cdp-1", memberIdentity.presetId, memberIdentity.targetEmail, memberIdentity.targetUserId,
      );
    });
    await waitFor(() => expect(hook.result.current.autoProgress?.phase).toBe("auth_prepared"), { timeout: 2_000 });
    await act(async () => { await Promise.all([first, second]); });

    expect(mock.requests.filter((item) => item.path === "/api/member-switch-runs/oauth-enrollments/auto")).toHaveLength(1);
    expect(readAuthEnrollmentLocator()).toBe(mock.enrollment?.id);
    mock.loseAutoEnrollmentResponse = false;
    await act(hook.result.current.refresh);
    expect(hook.result.current.oauthProbe?.accountId).toBe("auth-target");
  });

  it("keeps the stored enrollment visible when one-click automation requires manual auth", async () => {
    mock.autoEnrollmentResult = "manual";
    mock.catalog.workspaces[0].currentMembers = [{
      email: memberIdentity.targetEmail,
      userId: memberIdentity.targetUserId,
      presetId: memberIdentity.presetId,
      authState: "absent",
      authAccountId: null,
    }];
    const hook = await mount();
    await act(hook.result.current.loadCatalog);
    await act(() => hook.result.current.startAuthEnrollment(
      "cdp-1", memberIdentity.presetId, memberIdentity.targetEmail, memberIdentity.targetUserId,
    ));

    expect(hook.result.current.enrollment?.phase).toBe("auth_browser_opened");
    expect(hook.result.current.enrollment?.lastCode).toBe("ego_device_auth_user_action_required");
    expect(hook.result.current.enrollment?.allowedActions).toContain("advance_auth");
    expect(mock.requests.filter((item) => item.path === "/api/member-switch-runs/oauth-enrollments/auto")).toHaveLength(1);
  });
  it("probes after explicit OAuth finish recovery completes successfully", async () => {
    mock.enrollment = makeAuthEnrollmentView({
      phase: "auth_confirmed",
      authState: "completed",
      authAccountId: "auth-target",
      allowedActions: ["finish"],
    });
    const hook = await mount();

    await act(() => hook.result.current.enrollmentCommand("finish"));

    expect(hook.result.current.enrollment).toBeNull();
    expect(hook.result.current.oauthProbe?.accountId).toBe("auth-target");
    expect(mock.requests.filter((item) => item.path === "/api/accounts/auth-target/probe")).toHaveLength(0);
  });

  it("resumes a stored prepared enrollment with one automatic recovery request", async () => {
    mock.enrollment = makeAuthEnrollmentView({ phase: "prepared", allowedActions: ["prepare_auth", "cancel"] });
    const hook = await mount();
    expect(hook.result.current.enrollment?.phase).toBe("prepared");

    await act(hook.result.current.resumeAuthEnrollment);

    expect(hook.result.current.enrollment).toBeNull();
    expect(mock.requests.filter((item) => item.method === "POST" && /\/oauth-enrollments\/[^/]+\/auto$/.test(item.path))).toHaveLength(1);
    expect(mock.requests.filter((item) => item.path.endsWith("/commands"))).toHaveLength(0);
  });

  it("does not immediately repeat auto-resume when its terminal post-probe is still pending", async () => {
    mock.enrollment = makeAuthEnrollmentView({ phase: "prepared", allowedActions: ["prepare_auth", "cancel"] });
    mock.omitResumePostProbeOnce = true;
    const hook = await mount();
    expect(hook.result.current.enrollment?.phase).toBe("prepared");

    await act(hook.result.current.resumeAuthEnrollment);

    expect(hook.result.current.checked).toBe(false);
    expect(hook.result.current.enrollment?.phase).toBe("completed");
    expect(hook.result.current.oauthProbe?.errorCode).toBe("oauth_probe_recovery_required");
    expect(mock.requests.filter((item) => item.method === "POST" && /\/oauth-enrollments\/[^/]+\/auto$/.test(item.path))).toHaveLength(1);
    expect(mock.requests.filter((item) => item.path === "/api/accounts/auth-target/probe")).toHaveLength(0);

    await act(hook.result.current.refresh);

    expect(hook.result.current.checked).toBe(true);
    expect(hook.result.current.enrollment).toBeNull();
    expect(hook.result.current.oauthProbe?.state).toBe("completed");
    expect(mock.requests.filter((item) => item.method === "POST" && /\/oauth-enrollments\/[^/]+\/auto$/.test(item.path))).toHaveLength(2);
  });

  it("blocks catalog browser work after an unresolved create response", async () => {
    const hook = await mount(); mock.loseResponseFor = "create"; await preview(hook);
    expect(hook.result.current.checked).toBe(false);
    const before = mock.requests.filter(item => item.path.endsWith("/catalog/refresh")).length;
    await act(hook.result.current.loadCatalog);
    expect(mock.requests.filter(item => item.path.endsWith("/catalog/refresh"))).toHaveLength(before);
    await act(hook.result.current.refresh);
    expect(hook.result.current.flow?.id).toBe(mock.run?.id);
  });
  it("does not create a preview for an unconfirmed workspace", async () => {
    mock.catalog.workspaces[0].membershipCode = "ego_owner_profile_login_required";
    mock.catalog.workspaces[0].currentMembers = [];
    const hook = await mount(); await preview(hook);
    expect(mock.requests.filter(item => item.path === "/api/member-switch-runs")).toHaveLength(0);
    expect(hook.result.current.flow).toBeNull();
    expect(readRunLocator()).toBeNull();
  });
  it("rejects OAuth enrollment from failed observation even when a stale member is present", async () => {
    mock.catalog.workspaces[0].membershipCode = "ego_owner_identity_unavailable";
    mock.catalog.workspaces[0].currentMembers = [{ email: memberIdentity.targetEmail,
      userId: memberIdentity.targetUserId, presetId: memberIdentity.presetId, authState: "absent", authAccountId: null }];
    const hook = await mount(); await act(hook.result.current.loadCatalog);
    await act(() => hook.result.current.startAuthEnrollment("cdp-1", memberIdentity.presetId,
      memberIdentity.targetEmail, memberIdentity.targetUserId));
    expect(mock.requests.filter(item => item.method === "POST" && item.path.startsWith("/api/member-switch-runs/oauth-enrollments"))).toHaveLength(0);
  });

});
