import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api-client";
import {
  hasLegacyMemberFlow,
  readAuthEnrollmentLocator,
  readRunLocator,
  writeAuthEnrollmentLocator,
  writeRunLocator,
} from "@/features/member-switch/active-flow";
import {
  createAuthEnrollment, createRun, getActiveAuthEnrollment, getActiveRun, getAuthEnrollment, getRun,
  membershipObservationConfirmed, refreshRunCatalog, sendAuthEnrollmentCommand, sendRunCommand,
  type AuthEnrollmentAction, type AuthEnrollmentView, type RunAction, type RunCatalog, type RunView,
} from "@/features/member-switch/run-client";

export function memberSwitchErrorCode(error: unknown): string {
  return error instanceof Error && "code" in error && typeof error.code === "string" ? error.code : "request_failed";
}

function requireRunId(run: RunView, id: string): RunView {
  if (run.id !== id) throw new ApiError({ status: 0, code: "run_identity_mismatch", message: "Run identity mismatch" });
  return run;
}

async function readStoredState(signal: AbortSignal) {
  const runLocator = readRunLocator();
  const enrollmentLocator = readAuthEnrollmentLocator();
  const [activeRun, activeEnrollment] = await Promise.all([
    getActiveRun(signal),
    getActiveAuthEnrollment(signal),
  ]);
  signal.throwIfAborted();
  let run = activeRun.run;
  let enrollment = activeEnrollment.enrollment;
  if (!run && !enrollment && runLocator) {
    try { run = requireRunId(await getRun(runLocator, signal), runLocator); }
    catch (cause) {
      // A generic proxy/route 404 does not prove this run is absent.
      if (!(cause instanceof ApiError) || cause.status !== 404 || cause.code !== "run_not_found") throw cause;
    }
  }
  if (!run && !enrollment && enrollmentLocator) {
    try {
      const restored = await getAuthEnrollment(enrollmentLocator, signal);
      if (restored.id !== enrollmentLocator) throw new ApiError({ status: 0, code: "auth_enrollment_identity_mismatch", message: "Enrollment identity mismatch" });
      enrollment = restored;
    } catch (cause) {
      if (!(cause instanceof ApiError) || cause.status !== 404 || cause.code !== "auth_enrollment_not_found") throw cause;
    }
  }
  return { run, enrollment, runLocator, enrollmentLocator };
}

type RequestOwner = { action: string; controller: AbortController; timer?: number };

export function useMemberSwitch(readOnly: boolean) {
  const [flow, setFlow] = useState<RunView | null>(null);
  const [enrollment, setEnrollment] = useState<AuthEnrollmentView | null>(null);
  const [catalog, setCatalog] = useState<RunCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);
  const [legacy, setLegacy] = useState(false);
  const [accessSnapshot, setAccessSnapshot] = useState(readOnly);
  const active = useRef<RequestOwner | null>(null);
  const permission = useRef(false);

  // Reset UI state before rendering a different access lifecycle, not after paint.
  if (accessSnapshot !== readOnly) {
    setAccessSnapshot(readOnly);
    setFlow(null);
    setEnrollment(null);
    setCatalog(null);
    setChecked(false);
    setError(null);
    setBusy(null);
  }

  const run = useCallback(async <T,>(
    action: string,
    work: (signal: AbortSignal) => Promise<T>,
    publish: (result: T) => void,
  ): Promise<void> => {
    if (!permission.current) return;
    if (active.current) {
      // An operator can replace a slow initial GET, never an in-flight command.
      if (action !== "refresh" || active.current.action !== "restore") return;
      active.current.controller.abort();
      window.clearTimeout(active.current.timer);
    }
    const owner: RequestOwner = { action, controller: new AbortController() };
    active.current = owner;
    setBusy(action);
    setError(null);
    const storedRead = action === "restore" || action === "refresh";
    owner.timer = window.setTimeout(() => {
      owner.controller.abort();
      if (active.current !== owner) return;
      active.current = null;
      setBusy(null);
      setError(storedRead ? "status_request_timeout" : "command_response_timeout");
    }, storedRead ? 30_000 : 240_000);
    try {
      const result = await work(owner.controller.signal);
      if (active.current === owner && permission.current && !owner.controller.signal.aborted) publish(result);
    } catch (cause) {
      if (active.current === owner && permission.current) setError(memberSwitchErrorCode(cause));
    } finally {
      window.clearTimeout(owner.timer);
      if (active.current === owner) { active.current = null; setBusy(null); }
    }
  }, []);

  const restore = useCallback((action: "restore" | "refresh") => run(action, (signal) => {
    setChecked(false);
    return readStoredState(signal);
  }, ({ run: restored, enrollment: restoredEnrollment, runLocator, enrollmentLocator }) => {
    setFlow(restored);
    setEnrollment(restoredEnrollment);
    // A recovered terminal response may follow a lost finish reply. Stored-state
    // reads cannot make an older browser observation current again.
    if (restored?.phase === "completed" || restoredEnrollment?.phase === "completed") setCatalog(null);
    if (restored) writeRunLocator(restored.id);
    else if (readRunLocator() === runLocator) writeRunLocator(null);
    if (restoredEnrollment) writeAuthEnrollmentLocator(restoredEnrollment.id);
    else if (readAuthEnrollmentLocator() === enrollmentLocator) writeAuthEnrollmentLocator(null);
    setLegacy(hasLegacyMemberFlow());
    setChecked(true);
  }), [run]);

  useEffect(() => {
    permission.current = !readOnly;
    if (!readOnly) void restore("restore");
    return () => {
      permission.current = false;
      active.current?.controller.abort();
      window.clearTimeout(active.current?.timer);
      active.current = null;
    };
  }, [readOnly, restore]);

  const refresh = () => restore("refresh");
  const refreshCatalog = () => run("catalog", (signal) => {
    setCatalog(null);
    return refreshRunCatalog(signal);
  }, setCatalog);
  const loadCatalog = () => {
    if (!checked) return Promise.resolve();
    if ((flow && flow.phase !== "completed") || (enrollment && enrollment.phase !== "completed")) return Promise.resolve();
    return refreshCatalog();
  };
  const preview = (workspaceId: string, presetId: string) => {
    if (!checked || (flow !== null && flow.phase !== "completed") || (enrollment !== null && enrollment.phase !== "completed") || legacy || !catalog) return Promise.resolve();
    const workspace = catalog.workspaces.find(item => item.id === workspaceId);
    if (!catalog.enabled || !workspace || !membershipObservationConfirmed(workspace)
      || !workspace.members.some(member => member.presetId === presetId)) return Promise.resolve();
    return run("preview", async (signal) => {
      if (enrollment?.phase === "completed") {
        if (readAuthEnrollmentLocator() === enrollment.id) writeAuthEnrollmentLocator(null);
        setEnrollment(null);
      }
      const runId = crypto.randomUUID();
      writeRunLocator(runId);
      setChecked(false); // Aborting local waiting never proves server cancellation.
      return requireRunId(await createRun({ runId, workspaceId, presetId, catalogFingerprint: catalog.catalogFingerprint }, signal), runId);
    }, (result) => { setFlow(result); setChecked(true); });
  };
  const startAuthEnrollment = (
    workspaceId: string,
    presetId: string,
    memberEmail: string,
    memberUserId: string,
  ) => {
    if (!checked || !catalog || legacy || (flow && flow.phase !== "completed") || (enrollment && enrollment.phase !== "completed")) return Promise.resolve();
    const workspace = catalog.workspaces.find(item => item.id === workspaceId);
    if (!catalog.enabled || !workspace || !membershipObservationConfirmed(workspace)) return Promise.resolve();
    const current = workspace.currentMembers.find(member => member.presetId === presetId
      && member.email.toLowerCase() === memberEmail.toLowerCase() && member.userId === memberUserId);
    if (!current || !["absent", "inactive"].includes(current.authState)) return Promise.resolve();
    return run("oauth_enrollment_create", async (signal) => {
      if (flow?.phase === "completed") {
        if (readRunLocator() === flow.id) writeRunLocator(null);
        setFlow(null);
      }
      const enrollmentId = crypto.randomUUID();
      writeAuthEnrollmentLocator(enrollmentId);
      setChecked(false);
      const created = await createAuthEnrollment({
        enrollmentId, workspaceId, presetId, memberEmail, memberUserId,
        catalogFingerprint: catalog.catalogFingerprint,
      }, signal);
      if (created.id !== enrollmentId) throw new ApiError({ status: 0, code: "auth_enrollment_identity_mismatch", message: "Enrollment identity mismatch" });
      return created;
    }, (result) => { setEnrollment(result); setChecked(true); });
  };
  const enrollmentCommand = async (action: AuthEnrollmentAction) => {
    if (!checked || !enrollment || !enrollment.allowedActions.includes(action)) return Promise.resolve();
    let refreshAfterFinish = false;
    await run(`oauth_${action}`, async (signal) => {
      setChecked(false);
      const result = await sendAuthEnrollmentCommand(enrollment, action, signal);
      if (result.id !== enrollment.id) throw new ApiError({ status: 0, code: "auth_enrollment_identity_mismatch", message: "Enrollment identity mismatch" });
      return result;
    }, (result) => {
      setEnrollment(result);
      setChecked(true);
      if (action === "reconcile" && result.phase === "completed") setCatalog(null);
      if (action === "advance_auth" && result.phase === "auth_confirmed" && result.authState === "completed") {
        setCatalog((current) => current ? {
          ...current,
          workspaces: current.workspaces.map((workspace) => workspace.id === result.identity.workspaceId ? {
            ...workspace,
            currentMembers: workspace.currentMembers.map((member) =>
              member.email.toLowerCase() === result.identity.targetEmail && member.userId === result.identity.targetUserId
                ? { ...member, authState: "active" as const }
                : member),
          } : workspace),
        } : current);
      }
      refreshAfterFinish = action === "finish" && result.phase === "completed";
    });
    if (refreshAfterFinish) await refreshCatalog();
  };
  const command = async (action: RunAction) => {
    if (!checked || !flow || !flow.allowedActions.includes(action)) return Promise.resolve();
    let refreshAfterFinish = false;
    await run(action, async (signal) => {
      setChecked(false);
      return requireRunId(await sendRunCommand(flow, action, signal), flow.id);
    }, (result) => {
      setFlow(result);
      setChecked(true);
      if (
        action === "observe_membership" &&
        result.phase === "membership_confirmed" &&
        result.operation?.membershipState === "active"
      ) {
        setCatalog((current) => current ? {
          ...current,
          workspaces: current.workspaces.map((workspace) => workspace.id === result.identity.workspaceId ? {
            ...workspace,
            currentMembers: [{
              email: result.operation!.targetEmail,
              userId: result.operation!.targetUserId,
              presetId: result.identity.presetId,
              authState: "unknown",
              authAccountId: null,
            }],
            membershipCode: "confirmed_by_operation",
            membershipObservedAt: result.updatedAt,
          } : workspace),
        } : current);
      }
      const finished = action === "finish" && result.phase === "completed";
      // Pre-effect closeout frees ownership; it is not permission to reclaim a login Space.
      // Drop the stale catalog and leave the next browser-backed read explicitly to the user.
      const closedPreflightFailure = finished && flow.phase === "needs_attention";
      if (closedPreflightFailure || (action === "reconcile" && result.phase === "completed")) setCatalog(null);
      refreshAfterFinish = finished && !closedPreflightFailure;
    });
    if (refreshAfterFinish) await refreshCatalog();
  };
  const dismissFinished = () => {
    if (!active.current && permission.current && checked && flow?.phase === "completed") {
      if (readRunLocator() === flow.id) writeRunLocator(null);
      setFlow(null);
    }
  };
  const dismissFinishedEnrollment = () => {
    if (!active.current && permission.current && checked && enrollment?.phase === "completed") {
      if (readAuthEnrollmentLocator() === enrollment.id) writeAuthEnrollmentLocator(null);
      setEnrollment(null);
    }
  };
  return { flow: readOnly ? null : flow, enrollment: readOnly ? null : enrollment, catalog: readOnly ? null : catalog,
    error, busy, checked, legacy, refresh, loadCatalog, preview, command, dismissFinished,
    startAuthEnrollment, enrollmentCommand, dismissFinishedEnrollment };
}
