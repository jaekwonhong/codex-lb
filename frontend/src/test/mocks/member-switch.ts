import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import type {
  AuthEnrollmentAction, AuthEnrollmentView, RunAction, RunCatalog, RunView,
} from "@/features/member-switch/run-client";

export const memberIdentity = {
  workspaceId: "cdp-1", workspaceAccountId: "4865cea4-fb0b-41f3-917c-b226b2acdfb0",
  presetId: "cdp-1-target", targetEmail: "target@example.com", targetUserId: "user-Target123",
  catalogFingerprint: "a".repeat(64),
};
export function makeRunView(overrides: Partial<RunView> = {}): RunView {
  return {
    id: "bbf3ae1a-8dc1-4d99-b299-b55f2e4c0fa4", revision: 2, identity: memberIdentity,
    phase: "previewed", lastCode: "ready", updatedAt: "2026-09-06T01:00:00Z", pendingAction: null,
    allowedActions: ["start", "cancel"], removedEmail: null, operation: null, operationId: null,
    handoffId: null, authState: null, browserOperationId: null, ...overrides,
  };
}
export function makeAuthEnrollmentView(overrides: Partial<AuthEnrollmentView> = {}): AuthEnrollmentView {
  return {
    id: "3ab0ff43-1970-4e20-988e-acbba08b50b2", revision: 0, identity: memberIdentity,
    phase: "prepared", lastCode: "oauth_enrollment_ready", updatedAt: "2026-09-07T00:00:00Z",
    pendingAction: null, allowedActions: ["prepare_auth", "cancel"], handoffId: null, authState: null,
    authAccountId: null, postProbe: null, flowId: null, verificationUrl: null, userCode: null, expiresInSeconds: null,
    browserProfileId: null, browserTaskSpaceId: null, browserOwnership: null, ...overrides,
  };
}

export function installMemberSwitchMocks() {
  const state = {
    requests: [] as { method: string; path: string; body: unknown }[],
    catalog: {
      enabled: true, schemaVersion: 1, catalogFingerprint: memberIdentity.catalogFingerprint,
      capabilities: ["managed_member_switch_v1", "recipient_acceptance", "recipient_session_readiness", "post_add_device_auth", "durable_client_flow", "durable_participant_commands_v1"],
      workspaces: [{ id: "cdp-1", workspaceAccountId: memberIdentity.workspaceAccountId, workspaceName: "Test workspace",
        ownerEmail: "owner@example.com", members: [{ presetId: memberIdentity.presetId, displayName: "Target member",
          email: memberIdentity.targetEmail, userId: memberIdentity.targetUserId }],
        currentMembers: [{ email: "current@example.com", userId: "user-Current123", presetId: null,
          authState: "unmanaged" as const, authAccountId: null }],
        membershipCode: "ok", membershipObservedAt: "2026-09-07T00:00:00Z" }],
    } as RunCatalog,
    run: null as RunView | null,
    enrollment: null as AuthEnrollmentView | null,
    loseResponseFor: null as RunAction | "create" | null,
    autoEnrollmentResult: "completed" as "completed" | "manual",
    autoEnrollmentDelayMs: 0,
    loseAutoEnrollmentResponse: false,
    omitInitialPostProbeOnce: false,
    omitResumePostProbeOnce: false,
    probeErrorCode: null as string | null,
    probeStatusCode: 200,
    probePrimaryUsedPercentAfter: null as number | null,
  };
  const failure = (code: string, status = 409) => HttpResponse.json({ error: { code, message: code } }, { status });
  const postProbe = () => state.probeErrorCode
    ? { state: "failed" as const, accountId: "auth-target", probeStatusCode: null, primaryUsedPercentAfter: null,
        secondaryUsedPercentAfter: null, accountStatusAfter: null, errorCode: state.probeErrorCode }
    : { state: "completed" as const, accountId: "auth-target", probeStatusCode: state.probeStatusCode,
        primaryUsedPercentAfter: state.probePrimaryUsedPercentAfter, secondaryUsedPercentAfter: null,
        accountStatusAfter: "active", errorCode: null };
  async function respond(request: Request) {
    const path = new URL(request.url).pathname;
    const requestText = request.method === "POST" ? await request.text() : "";
    const body = requestText ? JSON.parse(requestText) as unknown : null;
    state.requests.push({ method: request.method, path, body });
    if (path.endsWith("/catalog") || path.endsWith("/catalog/refresh")) return HttpResponse.json(state.catalog);
    if (path.endsWith("/oauth-enrollments/active")) return HttpResponse.json({ enrollment: state.enrollment?.phase === "completed" ? null : state.enrollment });
    if (path === "/api/member-switch-runs/active") return HttpResponse.json({ run: state.run?.phase === "completed" ? null : state.run });
    if (path === "/api/member-switch-runs/oauth-enrollments/auto" && request.method === "POST") {
      const enrollmentId = (body as { enrollmentId: string }).enrollmentId;
      if (state.autoEnrollmentDelayMs > 0) {
        state.enrollment = makeAuthEnrollmentView({
          id: enrollmentId, revision: 2, phase: "auth_prepared", lastCode: "device_code_issued",
          authState: "device_code_issued", allowedActions: ["open_auth_browser"], handoffId: "handoff-enroll-1",
          flowId: "flow-enroll-1", verificationUrl: "https://auth.example/device", userCode: "ABCD-EFGH", expiresInSeconds: 900,
        });
        await new Promise((resolve) => setTimeout(resolve, state.autoEnrollmentDelayMs));
      }
      const initialPostProbe = state.omitInitialPostProbeOnce ? null : postProbe();
      state.omitInitialPostProbeOnce = false;
      state.enrollment = state.autoEnrollmentResult === "completed"
        ? makeAuthEnrollmentView({ id: enrollmentId, revision: 8, phase: "completed", lastCode: "auth_enrollment_finalized",
            authState: "completed", authAccountId: "auth-target", postProbe: initialPostProbe, allowedActions: [], handoffId: "handoff-enroll-1", flowId: "flow-enroll-1",
            verificationUrl: "https://auth.example/device", userCode: "ABCD-EFGH", expiresInSeconds: 900,
            browserProfileId: "CodexLB-account-target", browserTaskSpaceId: 17, browserOwnership: "agentDelegatedToUser" })
        : makeAuthEnrollmentView({ id: enrollmentId, revision: 4, phase: "auth_browser_opened",
            lastCode: "ego_device_auth_user_action_required", authState: "device_code_issued",
            allowedActions: ["advance_auth"], handoffId: "handoff-enroll-1", flowId: "flow-enroll-1",
            verificationUrl: "https://auth.example/device", userCode: "ABCD-EFGH", expiresInSeconds: 900,
            browserProfileId: "CodexLB-account-target", browserTaskSpaceId: 17, browserOwnership: "agentDelegatedToUser" });
      if (state.autoEnrollmentResult === "completed") {
        state.catalog.workspaces[0].currentMembers = [{ email: memberIdentity.targetEmail,
          userId: memberIdentity.targetUserId, presetId: memberIdentity.presetId, authState: "active", authAccountId: "auth-target" }];
      }
      if (state.loseAutoEnrollmentResponse) return HttpResponse.error();
      return HttpResponse.json(state.enrollment);
    }
    if (path === "/api/member-switch-runs/oauth-enrollments" && request.method === "POST") {
      const enrollmentId = (body as { enrollmentId: string }).enrollmentId;
      state.enrollment = makeAuthEnrollmentView({ id: enrollmentId });
      return HttpResponse.json(state.enrollment);
    }
    if (request.method === "POST" && /\/oauth-enrollments\/[^/]+\/auto$/.test(path)) {
      if (!state.enrollment) return failure("auth_enrollment_not_found", 404);
      const resumedPostProbe = state.omitResumePostProbeOnce ? null : postProbe();
      state.omitResumePostProbeOnce = false;
      state.enrollment = makeAuthEnrollmentView({ ...state.enrollment, revision: state.enrollment.revision + 8,
        phase: "completed", lastCode: "auth_enrollment_finalized", authState: "completed", authAccountId: "auth-target", postProbe: resumedPostProbe, allowedActions: [] });
      state.catalog.workspaces[0].currentMembers = [{ email: state.enrollment.identity.targetEmail,
        userId: state.enrollment.identity.targetUserId, presetId: state.enrollment.identity.presetId,
        authState: "active", authAccountId: "auth-target" }];
      return HttpResponse.json(state.enrollment);
    }
    if (path.includes("/oauth-enrollments/")) {
      if (!state.enrollment) return failure("auth_enrollment_not_found", 404);
      if (request.method === "GET") return HttpResponse.json(state.enrollment);
      const { action, expectedRevision } = body as { action: AuthEnrollmentAction; expectedRevision: number };
      if (state.enrollment.revision !== expectedRevision) return failure("revision_conflict");
      if (!state.enrollment.allowedActions.includes(action)) return failure("transition_not_allowed");
      const next = { ...state.enrollment, revision: state.enrollment.revision + 2 };
      if (action === "prepare_auth") Object.assign(next, { phase: "auth_prepared", lastCode: "device_code_issued",
        handoffId: "handoff-enroll-1", authState: "device_code_issued", flowId: "flow-enroll-1",
        verificationUrl: "https://auth.example/device", userCode: "ABCD-EFGH", expiresInSeconds: 900,
        allowedActions: ["open_auth_browser"] });
      if (action === "open_auth_browser") Object.assign(next, { phase: "auth_browser_opened",
        lastCode: "ego_task_space_handed_off", browserProfileId: "CodexLB-account-target",
        browserTaskSpaceId: 17, browserOwnership: "agentDelegatedToUser", allowedActions: ["advance_auth"] });
      if (action === "advance_auth") Object.assign(next, { phase: "auth_confirmed", lastCode: "completed",
        authState: "completed", allowedActions: ["finish"] });
      if (action === "finish" || action === "cancel") Object.assign(next, { phase: "completed",
        lastCode: action === "finish" ? "auth_enrollment_finalized" : "auth_enrollment_cancelled",
        ...(action === "finish" ? { authAccountId: "auth-target", postProbe: postProbe() } : {}), allowedActions: [] });
      state.enrollment = next;
      if (action === "finish") {
        state.catalog.workspaces[0].currentMembers = [{ email: memberIdentity.targetEmail,
          userId: memberIdentity.targetUserId, presetId: memberIdentity.presetId, authState: "active", authAccountId: "auth-target" }];
      }
      return HttpResponse.json(state.enrollment);
    }
    if (request.method === "GET") return state.run ? HttpResponse.json(state.run) : failure("run_not_found", 404);
    if (path === "/api/member-switch-runs") {
      if (state.run && state.run.phase !== "completed") return failure("flow_busy_or_id_exists");
      state.run = makeRunView({ id: (body as { runId: string }).runId });
      return state.loseResponseFor === "create" ? HttpResponse.error() : HttpResponse.json(state.run);
    }
    if (!state.run) return failure("run_not_found", 404);
    const { action, expectedRevision } = body as { action: RunAction; expectedRevision: number };
    if (state.run.revision !== expectedRevision) return failure("revision_conflict");
    if (!state.run.allowedActions.includes(action)) return failure("transition_not_allowed");
    const next = { ...state.run, revision: state.run.revision + 2 };
    if (action === "start" || action === "reconcile") Object.assign(next, { phase: "membership_requested", operationId: "operation-1", lastCode: "accepted", allowedActions: ["observe_membership"], pendingAction: null });
    if (action === "observe_membership") Object.assign(next, { phase: "membership_confirmed", operation: {
      operationId: "operation-1", stage: "completed", code: "member_added", targetEmail: memberIdentity.targetEmail,
      targetUserId: memberIdentity.targetUserId, membershipState: "active",
    }, allowedActions: ["observe_membership", "prepare_session"] });
    if (action === "prepare_session") Object.assign(next, next.handoffId
      ? { phase: "auth_prepared", allowedActions: ["observe_membership", "observe_auth", "advance_auth", "prepare_session", "open_browser"] }
      : { phase: "session_prepared", allowedActions: ["observe_membership", "prepare_session", "prepare_auth"] });
    if (action === "prepare_auth") Object.assign(next, { phase: "auth_prepared", handoffId: "handoff-1", authState: "device_code_issued", allowedActions: ["observe_auth", "advance_auth", "prepare_session", "open_browser"] });
    if (action === "open_browser") Object.assign(next, { phase: "auth_browser_opened", browserOperationId: "browser-1", allowedActions: ["observe_auth", "advance_auth", "close_browser"] });
    if (action === "advance_auth") Object.assign(next, { phase: "auth_confirmed", authState: "completed", allowedActions: ["observe_auth", ...(next.browserOperationId ? ["close_browser"] : ["finish"])] });
    if (action === "close_browser") Object.assign(next, { browserOperationId: null, lastCode: "closed",
      phase: next.authState === "completed" ? "auth_confirmed" : "needs_attention",
      allowedActions: next.authState === "completed" ? ["finish"] : ["observe_auth", "advance_auth", "prepare_session"] });
    if (action === "finish" || action === "cancel") Object.assign(next, { phase: "completed", lastCode: "run_finalized", allowedActions: [] });
    if (action === "finish") state.catalog.workspaces[0].currentMembers = [
      { email: memberIdentity.targetEmail, userId: memberIdentity.targetUserId, presetId: memberIdentity.presetId,
        authState: "active", authAccountId: "auth-target" },
    ];
    state.run = next;
    if (state.loseResponseFor === action) {
      state.run = { ...next, phase: "outcome_unknown", pendingAction: action, allowedActions: ["reconcile"] };
      return HttpResponse.error();
    }
    return HttpResponse.json(state.run);
  }
  server.use(
    http.all("/api/member-switch-runs", ({ request }) => respond(request)),
    http.all("/api/member-switch-runs/*", ({ request }) => respond(request)),
  );
  return state;
}
