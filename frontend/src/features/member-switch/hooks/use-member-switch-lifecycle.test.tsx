import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api-client";
import { readRunLocator, writeRunLocator } from "@/features/member-switch/active-flow";
import * as client from "@/features/member-switch/run-client";
import { installMemberSwitchMocks, makeRunView, makeAuthEnrollmentView } from "@/test/mocks/member-switch";
import { useMemberSwitch } from "./use-member-switch";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe("manual member-switch request ownership", () => {
  beforeEach(() => { localStorage.clear(); sessionStorage.clear(); installMemberSwitchMocks(); });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

  it("late restoration cannot overwrite a newer explicit refresh or its locator", async () => {
    const old = makeRunView();
    const current = makeRunView({ revision: 10, phase: "outcome_unknown", pendingAction: "start", allowedActions: ["reconcile"] });
    const first = deferred<{ run: client.RunView | null }>();
    const get = vi.spyOn(client, "getActiveRun").mockReturnValueOnce(first.promise).mockResolvedValue({ run: current });
    const hook = renderHook(() => useMemberSwitch(false));
    await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
    await act(hook.result.current.refresh);
    await act(async () => { first.resolve({ run: old }); });
    expect(hook.result.current.flow).toEqual(current);
    expect(readRunLocator()).toBe(current.id);
    expect(hook.result.current.checked).toBe(true);
  });

  it("a reply from before access revocation cannot overwrite restored state", async () => {
    const initial = makeRunView();
    const current = makeRunView({ revision: 20, phase: "outcome_unknown", pendingAction: "start", allowedActions: ["reconcile"] });
    const late = deferred<client.RunView>();
    vi.spyOn(client, "getActiveRun").mockResolvedValueOnce({ run: initial }).mockResolvedValue({ run: current });
    vi.spyOn(client, "sendRunCommand").mockReturnValue(late.promise);
    const hook = renderHook(({ readOnly }) => useMemberSwitch(readOnly), { initialProps: { readOnly: false } });
    await waitFor(() => expect(hook.result.current.checked).toBe(true));
    let pending!: Promise<void>;
    act(() => { pending = hook.result.current.command("start"); });
    hook.rerender({ readOnly: true });
    hook.rerender({ readOnly: false });
    await waitFor(() => expect(hook.result.current.flow?.revision).toBe(20));
    await act(async () => { late.resolve(makeRunView({ revision: 4, phase: "membership_requested" })); await pending; });
    expect(hook.result.current.flow).toEqual(current);
    expect(hook.result.current.checked).toBe(true);
    expect(hook.result.current.busy).toBeNull();
  });

  it("failed refresh retains the displayed run but disables stale commands", async () => {
    const current = makeRunView();
    const get = vi.spyOn(client, "getActiveRun").mockResolvedValue({ run: current });
    const send = vi.spyOn(client, "sendRunCommand");
    const hook = renderHook(() => useMemberSwitch(false));
    await waitFor(() => expect(hook.result.current.checked).toBe(true));
    get.mockRejectedValueOnce(new ApiError({ status: 503, code: "request_failed", message: "Unavailable" }));
    await act(hook.result.current.refresh);
    expect(hook.result.current.flow).toEqual(current);
    expect(hook.result.current.checked).toBe(false);
    await act(() => hook.result.current.command("start"));
    expect(send).not.toHaveBeenCalled();
    expect(readRunLocator()).toBe(current.id);
    await act(hook.result.current.refresh);
    expect(hook.result.current.checked).toBe(true);
  });

  it("confirmed missing locator restores idle on mount, just as on refresh", async () => {
    writeRunLocator(makeRunView().id);
    const hook = renderHook(() => useMemberSwitch(false));
    await waitFor(() => expect(hook.result.current.checked).toBe(true));
    expect(hook.result.current.error).toBeNull();
    expect(hook.result.current.flow).toBeNull();
    expect(readRunLocator()).toBeNull();
  });

  it("an unrelated 404 is not evidence to discard the stored locator", async () => {
    const id = makeRunView().id;
    writeRunLocator(id);
    vi.spyOn(client, "getRun").mockRejectedValue(new ApiError({ status: 404, code: "route_not_found", message: "Not found" }));
    const hook = renderHook(() => useMemberSwitch(false));
    await waitFor(() => expect(hook.result.current.error).toBe("route_not_found"));
    await act(hook.result.current.refresh);
    expect(readRunLocator()).toBe(id);
    expect(hook.result.current.checked).toBe(false);
  });

  it("timed-out restoration releases the UI but discards its eventual late reply", async () => {
    vi.useFakeTimers();
    const old = deferred<{ run: client.RunView | null }>();
    const current = makeRunView({ revision: 12 });
    vi.spyOn(client, "getActiveRun").mockReturnValueOnce(old.promise).mockResolvedValue({ run: current });
    const hook = renderHook(() => useMemberSwitch(false));
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(hook.result.current.error).toBe("status_request_timeout");
    expect(hook.result.current.busy).toBeNull();
    expect(hook.result.current.checked).toBe(false);
    await act(hook.result.current.refresh);
    await act(async () => { old.resolve({ run: makeRunView() }); });
    expect(hook.result.current.flow).toEqual(current);
    expect(hook.result.current.error).toBeNull();
  });

  it("an old missing lookup cannot clear a locator written by another tab", async () => {
    const first = makeRunView().id;
    const second = "05d27868-0446-4d7a-a29f-16bdd5c2335b";
    writeRunLocator(first);
    vi.spyOn(client, "getRun").mockImplementation(async () => {
      writeRunLocator(second);
      throw new ApiError({ status: 404, code: "run_not_found", message: "Missing" });
    });
    const hook = renderHook(() => useMemberSwitch(false));
    await waitFor(() => expect(hook.result.current.checked).toBe(true));
    expect(readRunLocator()).toBe(second);
  });

  it("create identity mismatch retains its requested locator and never enables commands", async () => {
    const create = vi.spyOn(client, "createRun").mockResolvedValue(makeRunView());
    const hook = renderHook(() => useMemberSwitch(false));
    await waitFor(() => expect(hook.result.current.checked).toBe(true));
    await act(hook.result.current.loadCatalog);
    await act(() => hook.result.current.preview("cdp-1", "cdp-1-target"));
    expect(hook.result.current.error).toBe("run_identity_mismatch");
    expect(hook.result.current.checked).toBe(false);
    expect(hook.result.current.flow).toBeNull();
    expect(readRunLocator()).toBe(create.mock.calls[0][0].runId);
  });
  it.each(["stored_refresh", "reconcile"])("recovered finish invalidates the prior catalog without browser reads (%s)", async (recovery) => {
    const failed = makeRunView({revision:6,phase:"needs_attention",lastCode:"ego_owner_profile_login_required",
      operationId:"operation-1",allowedActions:["observe_membership","finish"]});
    const completed = makeRunView({revision:10,phase:"completed",lastCode:"run_finalized",
      operationId:"operation-1",allowedActions:[]});
    const pending = makeRunView({revision:8,phase:"outcome_unknown",lastCode:"ego_owner_profile_login_required",
      operationId:"operation-1",pendingAction:"finish",allowedActions:["reconcile"]});
    const activeRun = vi.spyOn(client,"getActiveRun").mockResolvedValue({run:null});
    const read = vi.spyOn(client,"getRun").mockResolvedValue(completed);
    const catalog = vi.spyOn(client,"refreshRunCatalog");
    const send = vi.spyOn(client,"sendRunCommand").mockRejectedValueOnce(
      new ApiError({status:503,code:"request_failed",message:"Lost finalization response"})).mockResolvedValue(completed);
    const hook = renderHook(() => useMemberSwitch(false));
    await waitFor(() => expect(hook.result.current.checked).toBe(true));
    await act(hook.result.current.loadCatalog);
    expect(hook.result.current.catalog).not.toBeNull();
    activeRun.mockResolvedValue({run:failed});
    await act(hook.result.current.refresh);
    await act(() => hook.result.current.command("finish"));
    expect(hook.result.current.checked).toBe(false);
    activeRun.mockResolvedValue({run:recovery==="reconcile"?pending:null});
    await act(hook.result.current.refresh);
    if(recovery==="reconcile") await act(() => hook.result.current.command("reconcile"));
    expect(hook.result.current.flow?.phase).toBe("completed");
    expect(hook.result.current.checked).toBe(true);
    expect(hook.result.current.catalog).toBeNull();
    expect(catalog).toHaveBeenCalledTimes(1);
    if(recovery==="stored_refresh") expect(read).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledTimes(recovery==="reconcile"?2:1);
  });

  it.each(["stored_refresh", "reconcile"])("OAuth-only recovered finish discards the catalog without live reads (%s)", async (recovery) => {
    const initial = makeAuthEnrollmentView({revision:6,phase:"auth_confirmed",authState:"completed",allowedActions:["finish"]});
    const completed = makeAuthEnrollmentView({revision:10,phase:"completed",authState:"completed",authAccountId:"auth-target",
      postProbe:{state:"completed",accountId:"auth-target",probeStatusCode:200,primaryUsedPercentAfter:10,secondaryUsedPercentAfter:null,accountStatusAfter:"active",errorCode:null},
      lastCode:"auth_enrollment_finalized",allowedActions:[]});
    const pending = makeAuthEnrollmentView({revision:8,phase:"outcome_unknown",pendingAction:"finish",allowedActions:["reconcile"]});
    vi.spyOn(client,"getActiveRun").mockResolvedValue({run:null});
    const activeEnrollment=vi.spyOn(client,"getActiveAuthEnrollment").mockResolvedValue({enrollment:null});
    vi.spyOn(client,"getAuthEnrollment").mockResolvedValue(completed);
    const catalog=vi.spyOn(client,"refreshRunCatalog");
    const send=vi.spyOn(client,"sendAuthEnrollmentCommand").mockRejectedValueOnce(
      new ApiError({status:503,code:"request_failed",message:"Lost reply"})).mockResolvedValue(completed);
    const hook=renderHook(() => useMemberSwitch(false));
    await waitFor(() => expect(hook.result.current.checked).toBe(true));
    await act(hook.result.current.loadCatalog);
    activeEnrollment.mockResolvedValue({enrollment:initial});
    await act(hook.result.current.refresh);
    await act(() => hook.result.current.enrollmentCommand("finish"));
    expect(hook.result.current.checked).toBe(false);
    activeEnrollment.mockResolvedValue({enrollment:recovery==="reconcile"?pending:null});
    await act(hook.result.current.refresh);
    if(recovery==="reconcile") await act(() => hook.result.current.enrollmentCommand("reconcile"));
    expect(hook.result.current.enrollment).toBeNull();
    expect(hook.result.current.catalog).toBeNull();
    expect(catalog).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledTimes(recovery==="reconcile"?2:1);
    await act(hook.result.current.loadCatalog);
    expect(catalog).toHaveBeenCalledTimes(2);
  });

  it("failed restoration cannot be bypassed with a live catalog request", async () => {
    const read = vi.spyOn(client, "getActiveRun").mockRejectedValueOnce(
      new ApiError({status:503,code:"request_failed",message:"Unavailable"}));
    const refresh = vi.spyOn(client, "refreshRunCatalog");
    const hook = renderHook(() => useMemberSwitch(false));
    await waitFor(() => expect(hook.result.current.error).toBe("request_failed"));
    await act(hook.result.current.loadCatalog);
    expect(refresh).not.toHaveBeenCalled();
    read.mockResolvedValue({run:null});
    await act(hook.result.current.refresh);
    await act(hook.result.current.loadCatalog);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

});
