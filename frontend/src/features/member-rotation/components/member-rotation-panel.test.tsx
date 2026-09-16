import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getMemberRotationOperatorStatus,
  updateMemberRotationIntent,
} from "@/features/member-rotation/api";
import { MemberRotationPanel } from "@/features/member-rotation/components/member-rotation-panel";
import type {
  RotationOperatorResponse,
  RotationWorkspaceOperator,
} from "@/features/member-rotation/schemas";
import { renderWithProviders } from "@/test/utils";

vi.mock("@/features/member-rotation/api", () => ({
  getMemberRotationOperatorStatus: vi.fn(),
  updateMemberRotationIntent: vi.fn(),
}));

const getStatus = vi.mocked(getMemberRotationOperatorStatus);
const updateIntent = vi.mocked(updateMemberRotationIntent);

function workspace(
  id: string,
  overrides: Partial<RotationWorkspaceOperator> = {},
): RotationWorkspaceOperator {
  const base: RotationWorkspaceOperator = {
    workspaceId: id,
    workspaceAccountId: `workspace-account-${id}`,
    workspaceName: id,
    ownerEmail: `owner-${id}@example.com`,
    automaticRotationEnabled: false,
    controlVersion: 0,
    currentMember: {
      presetId: `${id}-current`,
      email: `current-${id}@example.com`,
      userId: `user-current-${id}`,
    },
    weeklyUsage: { state: "available", reason: null },
    fiveHourUsage: {
      state: "observed",
      usedPercent: 40,
      resetAt: 1_800_000_000,
      observedAt: "2026-09-13T10:00:00Z",
    },
    resetCredit: { state: "confirmed_no_redeemable_credit", detail: null },
    quota: {
      count24h: 2,
      limit24h: 3,
      count168h: 6,
      limit168h: 7,
      countBasis: "observed_local",
      historyComplete: false,
      coverageStartedAt: "2026-09-10T00:00:00Z",
    },
    foundation: {
      state: "usage_available",
      admissionReady: false,
      attentionRequired: false,
      weeklyState: "available",
      weeklyReason: null,
      resetStatus: null,
      quotaCode: null,
      count24h: null,
      count168h: null,
    },
    controller: {
      status: "idle",
      reason: null,
      removeEffect: null,
      inviteEffect: null,
      invitationIssued: false,
      membershipConfirmed: false,
      companionStatus: "ok",
    },
    nextCandidate: {
      presetId: `${id}-next`,
      email: `next-${id}@example.com`,
      userId: `user-next-${id}`,
    },
    blockerCodes: [],
    history: [],
  };
  return {
    ...base,
    ...overrides,
    weeklyUsage: { ...base.weeklyUsage, ...overrides.weeklyUsage },
    fiveHourUsage: { ...base.fiveHourUsage, ...overrides.fiveHourUsage },
    resetCredit: { ...base.resetCredit, ...overrides.resetCredit },
    quota: { ...base.quota, ...overrides.quota },
    controller: { ...base.controller, ...overrides.controller },
  };
}

function response(workspaces: RotationWorkspaceOperator[]): RotationOperatorResponse {
  return { schemaVersion: 1, workspaces };
}

describe("member rotation operator panel", () => {
  beforeEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
    updateIntent.mockResolvedValue({
      workspaceId: "workspace-a",
      workspaceAccountId: "workspace-account-workspace-a",
      enabled: true,
      version: 1,
    });
  });

  it("does not query identity-bearing operator state without accounts:write", () => {
    renderWithProviders(<MemberRotationPanel readOnly />);
    expect(screen.getByText(/accounts:write 권한이 필요합니다/)).toBeInTheDocument();
    expect(getStatus).not.toHaveBeenCalled();
    expect(updateIntent).not.toHaveBeenCalled();
  });

  it.each([
    [2, 3, 6, 7],
    [3, 3, 7, 7],
  ])("renders internal observed quota %i/%i and %i/%i without claiming an OpenAI limit", async (day, dayLimit, week, weekLimit) => {
    getStatus.mockResolvedValue(response([
      workspace("workspace-a", {
        quota: {
          count24h: day,
          limit24h: dayLimit,
          count168h: week,
          limit168h: weekLimit,
          countBasis: "observed_local",
          historyComplete: false,
          coverageStartedAt: "2026-09-10T00:00:00Z",
        },
      }),
    ]));
    renderWithProviders(<MemberRotationPanel readOnly={false} />);

    const card = await screen.findByTestId("rotation-workspace-workspace-a");
    expect(within(card).getByText(`24H ${day} / ${dayLimit}`)).toBeInTheDocument();
    expect(within(card).getByText(`7D ${week} / ${weekLimit}`)).toBeInTheDocument();
    expect(within(card).getByText("Observed locally")).toBeInTheDocument();
    expect(within(card).getByText(/외부 수동 member change/)).toBeInTheDocument();
    expect(within(card).queryByText(/OpenAI limit/i)).not.toBeInTheDocument();
  });

  it.each([
    ["usage_unknown", "Usage 미확인"],
    ["usage_available", "Usage 사용 가능"],
    ["reset_required", "Reset 해결 필요"],
    ["reset_recovered", "Reset 후 회복"],
    ["reset_reconciliation_pending", "Reset reconciliation 대기"],
    ["reset_unavailable", "Reset 확인 필요"],
    ["quota_required", "내부 guard 확인 필요"],
    ["quota_blocked", "내부 guard 차단"],
    ["admission_ready", "Foundation 준비됨"],
    ["invalid_evidence", "증거 무효"],
  ] as const)("renders foundation state %s from the server read model", async (state, label) => {
    getStatus.mockResolvedValue(response([
      workspace("workspace-a", {
        foundation: {
          state,
          admissionReady: state === "admission_ready",
          attentionRequired: [
            "usage_unknown",
            "reset_reconciliation_pending",
            "reset_unavailable",
            "quota_blocked",
            "invalid_evidence",
          ].includes(state),
          weeklyState: "unknown",
          weeklyReason: "fixture",
          resetStatus: null,
          quotaCode: null,
          count24h: null,
          count168h: null,
        },
      }),
    ]));
    renderWithProviders(<MemberRotationPanel readOnly={false} />);
    expect(await screen.findByText(`Foundation: ${label}`)).toBeInTheDocument();
  });

  it("renders G1 Weekly unknown separately from confirmed exhausted and reset pending separately from recovered", async () => {
    getStatus.mockResolvedValue(response([
      workspace("unknown", {
        weeklyUsage: { state: "unknown", reason: "reset_elapsed" },
        resetCredit: { state: "reconciliation_pending", detail: null },
        foundation: {
          state: "reset_reconciliation_pending",
          admissionReady: false,
          attentionRequired: true,
          weeklyState: "unknown",
          weeklyReason: "reset_elapsed",
          resetStatus: "reconciliation_pending",
          quotaCode: null,
          count24h: null,
          count168h: null,
        },
        blockerCodes: ["reset_reconciliation_pending"],
      }),
      workspace("exhausted", {
        weeklyUsage: { state: "exhausted", reason: null },
        resetCredit: { state: "usage_recovered", detail: null },
        foundation: {
          state: "reset_recovered",
          admissionReady: false,
          attentionRequired: false,
          weeklyState: "exhausted",
          weeklyReason: null,
          resetStatus: "usage_recovered",
          quotaCode: null,
          count24h: null,
          count168h: null,
        },
      }),
    ]));
    renderWithProviders(<MemberRotationPanel readOnly={false} />);

    const unknown = await screen.findByTestId("rotation-workspace-unknown");
    const exhausted = screen.getByTestId("rotation-workspace-exhausted");
    expect(within(unknown).getByText("미확인 · reset 시각 경과")).toBeInTheDocument();
    expect(within(unknown).getByText("Reconciliation 대기")).toBeInTheDocument();
    expect(within(exhausted).getByText("소진 확인됨")).toBeInTheDocument();
    expect(within(exhausted).getByText("회복 확인됨")).toBeInTheDocument();
  });

  it("keeps removed-member final Usage immutable and distinguishes original from invalidated effective reset", async () => {
    getStatus.mockResolvedValue(response([
      workspace("history", {
        history: [{
          email: "removed@example.com",
          userId: "user-removed",
          presetId: "removed-preset",
          membershipEpoch: "epoch-1",
          removedAt: "2026-09-12T09:30:00Z",
          retainedAt: "2026-09-12T09:29:58Z",
          fiveHour: {
            logicalWindow: "5h",
            sourceWindow: "primary",
            usedPercent: 98.5,
            originalResetAt: 1_800_000_000,
            effectiveResetAt: null,
            observedAt: "2026-09-12T09:29:50Z",
            retainedAt: "2026-09-12T09:29:58Z",
            resetScheduleInvalidated: true,
          },
          weekly: {
            logicalWindow: "weekly",
            sourceWindow: "secondary",
            usedPercent: 100,
            originalResetAt: 1_800_500_000,
            effectiveResetAt: null,
            observedAt: "2026-09-12T09:29:50Z",
            retainedAt: "2026-09-12T09:29:58Z",
            resetScheduleInvalidated: true,
          },
        }],
      }),
    ]));
    renderWithProviders(<MemberRotationPanel readOnly={false} />);

    const card = await screen.findByTestId("rotation-workspace-history");
    expect(within(card).getByText("5H final Usage: 98.5%")).toBeInTheDocument();
    expect(within(card).getByText("Weekly final Usage: 100.0%")).toBeInTheDocument();
    expect(within(card).getAllByText(/Original Reset:/)).toHaveLength(2);
    expect(within(card).getAllByText("Effective Reset: —")).toHaveLength(2);
    expect(within(card).getAllByText(/원본 증거는 보존됨/)).toHaveLength(2);
  });

  it("defaults automatic rotation to OFF and writes intent only after an explicit toggle", async () => {
    const user = userEvent.setup();
    getStatus.mockResolvedValue(response([workspace("workspace-a")]));
    renderWithProviders(<MemberRotationPanel readOnly={false} />);

    const toggle = await screen.findByRole("switch", { name: "workspace-a 자동 멤버 교체" });
    expect(toggle).not.toBeChecked();
    expect(updateIntent).not.toHaveBeenCalled();
    await user.click(toggle);
    expect(updateIntent).toHaveBeenCalledWith("workspace-a", { enabled: true, expectedVersion: 0 });
  });

  it("page load, focus, and status polling never call the intent mutation", async () => {
    vi.useFakeTimers();
    getStatus.mockResolvedValue(response([workspace("workspace-a")]));
    renderWithProviders(<MemberRotationPanel readOnly={false} />);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(getStatus).toHaveBeenCalledTimes(1);
    expect(updateIntent).not.toHaveBeenCalled();

    act(() => window.dispatchEvent(new Event("focus")));
    await act(async () => { await Promise.resolve(); });
    expect(updateIntent).not.toHaveBeenCalled();

    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(getStatus.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(updateIntent).not.toHaveBeenCalled();
  });

  it("hides an owner identity if it is ever reported as the next candidate", async () => {
    getStatus.mockResolvedValue(response([
      workspace("workspace-a", {
        ownerEmail: "owner@example.com",
        nextCandidate: {
          presetId: "owner-preset",
          email: "owner@example.com",
          userId: "owner-user",
        },
      }),
    ]));
    renderWithProviders(<MemberRotationPanel readOnly={false} />);
    const card = await screen.findByTestId("rotation-workspace-workspace-a");
    expect(within(card).getByText("Next candidate: controller가 보고하지 않음")).toBeInTheDocument();
  });

  it("does not conflate invitation sent with authoritative membership confirmation", async () => {
    getStatus.mockResolvedValue(response([
      workspace("workspace-a", {
        controller: {
          status: "rotating",
          reason: null,
          removeEffect: "confirmed",
          inviteEffect: "confirmed",
          invitationIssued: true,
          membershipConfirmed: false,
          companionStatus: "ok",
        },
      }),
    ]));
    renderWithProviders(<MemberRotationPanel readOnly={false} />);
    expect(await screen.findByText("Invite 전송됨 · 멤버십 등록은 아직 미확인")).toBeInTheDocument();
    expect(screen.queryByText("멤버십 등록 확인됨")).not.toBeInTheDocument();
  });

  it("keeps all safety attention states visible without an effect retry control", async () => {
    getStatus.mockResolvedValue(response([
      workspace("workspace-a", {
        automaticRotationEnabled: true,
        blockerCodes: [
          "usage_unknown",
          "reset_reconciliation_pending",
          "reset_unavailable",
          "invalid_evidence",
          "quota_blocked",
          "unknown_remove_effect",
          "unknown_invite_effect",
          "companion_capability_mismatch",
          "companion_provenance_mismatch",
        ],
        controller: {
          status: "needs_attention",
          reason: "unknown_invite_effect",
          removeEffect: "unknown",
          inviteEffect: "unknown",
          invitationIssued: null,
          membershipConfirmed: null,
          companionStatus: "provenance_mismatch",
        },
      }),
    ]));
    renderWithProviders(<MemberRotationPanel readOnly={false} />);
    const card = await screen.findByTestId("rotation-workspace-workspace-a");
    expect(within(card).getByText(/Remove 요청의 실제 효과/)).toBeInTheDocument();
    expect(within(card).getAllByText(/Invite 요청의 실제 효과/)).toHaveLength(2);
    expect(within(card).getByText(/Reason: Invite 요청의 실제 효과/)).toBeInTheDocument();
    expect(within(card).getByText(/Companion capability/)).toBeInTheDocument();
    expect(within(card).getByText(/Companion provenance/)).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: /retry|재시도|remove|invite/i })).not.toBeInTheDocument();
  });
});
