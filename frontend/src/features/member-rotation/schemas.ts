import { z } from "zod";

export const FoundationStateSchema = z.enum([
  "usage_unknown",
  "usage_available",
  "reset_required",
  "reset_recovered",
  "reset_reconciliation_pending",
  "reset_unavailable",
  "quota_required",
  "quota_blocked",
  "admission_ready",
  "invalid_evidence",
]);

export const WeeklyStateSchema = z.enum(["unknown", "available", "exhausted"]);
export const FiveHourStateSchema = z.enum(["observed", "unknown", "stale", "missing"]);
export const ResetOperatorStateSchema = z.enum([
  "resolution_required",
  "redeem_in_progress",
  "confirmed_no_redeemable_credit",
  "usage_recovered",
  "reconciliation_pending",
  "unavailable",
  "unknown",
]);

export const RotationOperatorMemberSchema = z.object({
  presetId: z.string().min(1),
  email: z.string().min(3),
  userId: z.string().min(1),
});

export const RotationWeeklyUsageSchema = z.object({
  state: WeeklyStateSchema,
  reason: z.string().nullable(),
});

export const RotationFiveHourUsageSchema = z.object({
  state: FiveHourStateSchema,
  usedPercent: z.number().nullable(),
  resetAt: z.number().int().nullable(),
  observedAt: z.string().nullable(),
});

export const RotationResetSchema = z.object({
  state: ResetOperatorStateSchema,
  detail: z.string().nullable(),
});

export const RotationFoundationSchema = z.object({
  state: FoundationStateSchema,
  admissionReady: z.boolean(),
  attentionRequired: z.boolean(),
  weeklyState: WeeklyStateSchema,
  weeklyReason: z.string().nullable(),
  resetStatus: z.string().nullable(),
  quotaCode: z.string().nullable(),
  count24h: z.number().int().nullable(),
  count168h: z.number().int().nullable(),
});

export const RotationQuotaSchema = z.object({
  count24h: z.number().int().nonnegative(),
  limit24h: z.number().int().positive(),
  count168h: z.number().int().nonnegative(),
  limit168h: z.number().int().positive(),
  countBasis: z.string(),
  historyComplete: z.boolean(),
  coverageStartedAt: z.string().nullable(),
});

export const HistoricalUsageWindowSchema = z.object({
  logicalWindow: z.enum(["5h", "weekly"]),
  sourceWindow: z.string(),
  usedPercent: z.number(),
  originalResetAt: z.number().int().nullable(),
  effectiveResetAt: z.number().int().nullable(),
  observedAt: z.string(),
  retainedAt: z.string(),
  resetScheduleInvalidated: z.boolean(),
});

export const RemovedMemberHistorySchema = z.object({
  email: z.string(),
  userId: z.string(),
  presetId: z.string(),
  membershipEpoch: z.string(),
  removedAt: z.string().nullable(),
  retainedAt: z.string(),
  fiveHour: HistoricalUsageWindowSchema.nullable(),
  weekly: HistoricalUsageWindowSchema.nullable(),
});

export const RotationControllerSchema = z.object({
  status: z.string(),
  reason: z.string().nullable(),
  removeEffect: z.string().nullable(),
  inviteEffect: z.string().nullable(),
  invitationIssued: z.boolean().nullable(),
  membershipConfirmed: z.boolean().nullable(),
  companionStatus: z.string().nullable(),
});

export const RotationWorkspaceOperatorSchema = z.object({
  workspaceId: z.string(),
  workspaceAccountId: z.string(),
  workspaceName: z.string(),
  ownerEmail: z.string(),
  automaticRotationEnabled: z.boolean(),
  controlVersion: z.number().int().nonnegative(),
  currentMember: RotationOperatorMemberSchema.nullable(),
  weeklyUsage: RotationWeeklyUsageSchema,
  fiveHourUsage: RotationFiveHourUsageSchema,
  resetCredit: RotationResetSchema,
  quota: RotationQuotaSchema,
  foundation: RotationFoundationSchema.nullable(),
  controller: RotationControllerSchema,
  nextCandidate: RotationOperatorMemberSchema.nullable(),
  blockerCodes: z.array(z.string()),
  history: z.array(RemovedMemberHistorySchema),
});

export const RotationOperatorResponseSchema = z.object({
  schemaVersion: z.literal(1),
  workspaces: z.array(RotationWorkspaceOperatorSchema),
});

export const RotationIntentUpdateRequestSchema = z.object({
  enabled: z.boolean(),
  expectedVersion: z.number().int().nonnegative(),
});

export const RotationIntentViewSchema = z.object({
  workspaceId: z.string(),
  workspaceAccountId: z.string(),
  enabled: z.boolean(),
  version: z.number().int().positive(),
});

export type RotationOperatorResponse = z.infer<typeof RotationOperatorResponseSchema>;
export type RotationWorkspaceOperator = z.infer<typeof RotationWorkspaceOperatorSchema>;
export type HistoricalUsageWindow = z.infer<typeof HistoricalUsageWindowSchema>;
export type RotationIntentUpdateRequest = z.infer<typeof RotationIntentUpdateRequestSchema>;
