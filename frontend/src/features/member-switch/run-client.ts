import { z } from "zod";
import { get, post } from "@/lib/api-client";

const ROOT = "/api/member-switch-runs";
export const RunActionSchema = z.enum([
  "start", "observe_membership", "prepare_session", "prepare_auth", "open_browser", "observe_auth",
  "advance_auth", "close_browser", "finish", "cancel", "reconcile",
]);
const IdentitySchema = z.object({
  workspaceId: z.string(), workspaceAccountId: z.string(), presetId: z.string(),
  targetEmail: z.string(), targetUserId: z.string(), catalogFingerprint: z.string(),
});
export const RunCatalogSchema = z.object({
  enabled: z.boolean(), schemaVersion: z.literal(1), catalogFingerprint: z.string(), capabilities: z.array(z.string()),
  workspaces: z.array(z.object({
    id: z.string(), workspaceAccountId: z.string(), workspaceName: z.string(), ownerEmail: z.string(),
    ownerAuth: z.object({
      presetId: z.string(), email: z.string(), userId: z.string(),
      authState: z.enum(["active", "handoff_quarantined", "inactive", "absent", "ambiguous", "unmanaged", "unknown"]).default("unknown"),
      authAccountId: z.string().nullable().default(null),
    }).nullable().default(null),
    members: z.array(z.object({ presetId: z.string(), displayName: z.string(), email: z.string(), userId: z.string() })),
    currentMembers: z.array(z.object({
      email: z.string(), userId: z.string(), presetId: z.string().nullable().default(null),
      authState: z.enum(["active", "handoff_quarantined", "inactive", "absent", "ambiguous", "unmanaged", "unknown"]).default("unknown"),
      authAccountId: z.string().nullable().default(null),
    })).default([]),
    membershipCode: z.string().default("not_checked"),
    membershipObservedAt: z.string().nullable().default(null),
  })),
});
export const RunViewSchema = z.object({
  id: z.uuid(), revision: z.number().int().nonnegative(), identity: IdentitySchema,
  phase: z.enum(["previewed", "membership_requested", "membership_confirmed", "session_prepared", "auth_prepared",
    "auth_browser_opened", "auth_confirmed", "completed", "needs_attention", "failed", "outcome_unknown"]),
  lastCode: z.string(), updatedAt: z.iso.datetime({ offset: true }), pendingAction: z.string().nullable(),
  allowedActions: z.array(RunActionSchema), removedEmail: z.string().nullable(),
  operationId: z.string().nullable(), handoffId: z.string().nullable(), authState: z.string().nullable(),
  browserOperationId: z.string().nullable(),
  operation: z.object({
    operationId: z.string(), stage: z.string(), code: z.string(),
    targetEmail: z.string(), targetUserId: z.string(), membershipState: z.string(),
  }).nullable(),
});
export type RunAction = z.infer<typeof RunActionSchema>;
export type RunView = z.infer<typeof RunViewSchema>;
export type RunCatalog = z.infer<typeof RunCatalogSchema>;

export function membershipObservationConfirmed(workspace: RunCatalog["workspaces"][number]): boolean {
  return ["ok", "confirmed_by_operation"].includes(workspace.membershipCode)
    && workspace.membershipObservedAt !== null;
}


export const AuthEnrollmentActionSchema = z.enum([
  "prepare_auth", "open_auth_browser", "advance_auth", "finish", "cancel", "reconcile",
]);
export const AuthEnrollmentPostProbeSchema = z.object({
  state: z.enum(["completed", "failed"]),
  accountId: z.string().nullable().default(null),
  probeStatusCode: z.number().int().nullable().default(null),
  primaryUsedPercentAfter: z.number().nullable().default(null),
  secondaryUsedPercentAfter: z.number().nullable().default(null),
  accountStatusAfter: z.string().nullable().default(null),
  usageRefreshSucceeded: z.boolean().nullable().default(null),
  errorCode: z.string().nullable().default(null),
});
export const AuthEnrollmentViewSchema = z.object({
  id: z.uuid(), revision: z.number().int().nonnegative(), identity: IdentitySchema,
  phase: z.enum(["prepared", "auth_prepared", "auth_browser_opened", "auth_confirmed", "completed", "needs_attention", "outcome_unknown"]),
  lastCode: z.string(), updatedAt: z.iso.datetime({ offset: true }), pendingAction: z.string().nullable(),
  allowedActions: z.array(AuthEnrollmentActionSchema), handoffId: z.string().nullable(), authState: z.string().nullable(),
  authAccountId: z.string().nullable().default(null), postProbe: AuthEnrollmentPostProbeSchema.nullable().default(null),
  flowId: z.string().nullable(), verificationUrl: z.string().nullable(), userCode: z.string().nullable(),
  expiresInSeconds: z.number().int().nullable(),
  browserProfileId: z.string().nullable(), browserTaskSpaceId: z.number().int().nullable(),
  browserOwnership: z.string().nullable(),
});
export type AuthEnrollmentAction = z.infer<typeof AuthEnrollmentActionSchema>;
export type AuthEnrollmentPostProbe = z.infer<typeof AuthEnrollmentPostProbeSchema>;
export type AuthEnrollmentView = z.infer<typeof AuthEnrollmentViewSchema>;

export function getActiveRun(signal?: AbortSignal) {
  return get(`${ROOT}/active`, z.object({ run: RunViewSchema.nullable() }), { signal, cache: "no-store" });
}
export function getRun(id: string, signal?: AbortSignal) {
  return get(`${ROOT}/${encodeURIComponent(id)}`, RunViewSchema, { signal, cache: "no-store" });
}
export function getRunCatalog(signal?: AbortSignal) {
  return get(`${ROOT}/catalog`, RunCatalogSchema, { signal, cache: "no-store" });
}
export function refreshRunCatalog(signal?: AbortSignal) {
  return post(`${ROOT}/catalog/refresh`, RunCatalogSchema, { signal });
}
export function createRun(body: { runId: string; workspaceId: string; presetId: string; catalogFingerprint: string }, signal?: AbortSignal) {
  return post(ROOT, RunViewSchema, { body, signal });
}
export function sendRunCommand(run: RunView, action: RunAction, signal?: AbortSignal) {
  return post(`${ROOT}/${encodeURIComponent(run.id)}/commands`, RunViewSchema, {
    signal, body: { commandId: crypto.randomUUID(), expectedRevision: run.revision, action },
  });
}

export function getActiveAuthEnrollment(signal?: AbortSignal) {
  return get(`${ROOT}/oauth-enrollments/active`, z.object({ enrollment: AuthEnrollmentViewSchema.nullable() }), {
    signal, cache: "no-store",
  });
}

export function getAuthEnrollment(id: string, signal?: AbortSignal) {
  return get(`${ROOT}/oauth-enrollments/${encodeURIComponent(id)}`, AuthEnrollmentViewSchema, { signal, cache: "no-store" });
}

export function autoCompleteAuthEnrollment(body: {
  enrollmentId: string; workspaceId: string; presetId: string; memberEmail: string; memberUserId: string; catalogFingerprint: string;
}, signal?: AbortSignal) {
  return post(`${ROOT}/oauth-enrollments/auto`, AuthEnrollmentViewSchema, { body, signal });
}

export function resumeAutoAuthEnrollment(enrollmentId: string, signal?: AbortSignal) {
  return post(`${ROOT}/oauth-enrollments/${encodeURIComponent(enrollmentId)}/auto`, AuthEnrollmentViewSchema, { signal });
}

export function sendAuthEnrollmentCommand(enrollment: AuthEnrollmentView, action: AuthEnrollmentAction, signal?: AbortSignal) {
  return post(`${ROOT}/oauth-enrollments/${encodeURIComponent(enrollment.id)}/commands`, AuthEnrollmentViewSchema, {
    signal, body: { commandId: crypto.randomUUID(), expectedRevision: enrollment.revision, action },
  });
}
