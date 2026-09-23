import { AlertTriangle, History, RefreshCw, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useMemberRotationOperator } from "@/features/member-rotation/hooks/use-member-rotation";
import type {
  HistoricalUsageWindow,
  RotationWorkspaceOperator,
} from "@/features/member-rotation/schemas";

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatEpoch(value: number | null | undefined): string {
  if (value == null) return "—";
  const date = new Date(value * 1000);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function weeklyLabel(workspace: RotationWorkspaceOperator): string {
  const { state, reason } = workspace.weeklyUsage;
  if (state === "exhausted") return "소진 확인됨";
  if (state === "available") return "사용 가능";
  if (reason === "reset_elapsed") return "미확인 · reset 시각 경과";
  if (reason === "stale") return "미확인 · stale";
  if (reason === "weekly_missing") return "미확인 · Weekly 누락";
  if (reason === "usage_missing") return "미확인 · Usage 누락";
  return `미확인${reason ? ` · ${reason}` : ""}`;
}

function resetLabel(state: RotationWorkspaceOperator["resetCredit"]["state"]): string {
  switch (state) {
    case "resolution_required":
      return "Reset credit 확인/해결 필요";
    case "redeem_in_progress":
      return "Redeem 진행 중";
    case "reconciliation_pending":
      return "Reconciliation 대기";
    case "usage_recovered":
      return "회복 확인됨";
    case "confirmed_no_redeemable_credit":
      return "사용 가능한 credit 없음 확인";
    case "unavailable":
      return "확인 필요";
    default:
      return "미확인";
  }
}

function foundationLabel(state: string | undefined): string {
  const labels: Record<string, string> = {
    usage_unknown: "Usage 미확인",
    usage_available: "Usage 사용 가능",
    reset_required: "Reset 해결 필요",
    reset_recovered: "Reset 후 회복",
    reset_reconciliation_pending: "Reset reconciliation 대기",
    reset_unavailable: "Reset 확인 필요",
    quota_required: "내부 guard 확인 필요",
    quota_blocked: "내부 guard 차단",
    admission_ready: "Foundation 준비됨",
    invalid_evidence: "증거 무효",
  };
  return state ? (labels[state] ?? state) : "연동 대기";
}

function blockerLabel(code: string): string {
  const labels: Record<string, string> = {
    usage_unknown: "Weekly Usage가 확정되지 않았습니다.",
    reset_reconciliation_pending: "Reset 결과의 fresh Usage reconciliation이 끝나지 않았습니다.",
    reset_unavailable: "Reset-credit resolution을 확인할 수 없습니다.",
    invalid_evidence: "Foundation 증거가 현재 member identity와 일치하지 않습니다.",
    quota_blocked: "내부 rotation guard가 현재 교체를 허용하지 않습니다.",
    unknown_remove_effect: "Remove 요청의 실제 효과가 아직 확정되지 않았습니다.",
    unknown_invite_effect: "Invite 요청의 실제 효과가 아직 확정되지 않았습니다.",
    companion_capability_mismatch: "Companion capability가 controller 요구사항과 맞지 않습니다.",
    companion_provenance_mismatch: "Companion provenance가 확인되지 않았습니다.",
    controller_snapshot_unavailable: "Controller 상태 snapshot이 아직 연결되지 않았습니다.",
    invalid_next_candidate: "Controller가 보고한 다음 후보가 등록된 member 후보와 일치하지 않습니다.",
    rotation_prestart_interrupted_requires_attention: "교체 시작 전 작업이 중단되어 운영자 복구가 필요합니다.",
  };
  return labels[code] ?? code;
}

function UsageHistoryWindow({ label, value, fiveHourState }: {
  label: string;
  value: HistoricalUsageWindow | null;
  fiveHourState?: RotationWorkspaceOperator["history"][number]["fiveHourState"];
}) {
  const notProvided = label === "5H" && fiveHourState === "not_provided";
  const unverified = label === "5H" && fiveHourState !== "observed";
  if (notProvided || !value) {
    return (
      <div className="rounded-md border p-3 text-xs text-muted-foreground">
        <p className="font-medium text-foreground">{label}</p>
        <p className="mt-1">{notProvided ? "미제공 · 해당 조회 응답에 5H 없음" : "미확인 · Final Usage evidence 없음"}</p>
      </div>
    );
  }
  return (
    <div className="rounded-md border p-3 text-xs">
      {unverified ? (
        <p className="font-medium text-amber-700 dark:text-amber-300">{label} 미확인 · Final Usage evidence 검증 불가</p>
      ) : null}
      <p className="font-medium">
        {unverified ? `${label} 보존된 원본 Usage (미검증)` : `${label} final Usage`}: {value.usedPercent.toFixed(1)}%
      </p>
      <p className="mt-1 text-muted-foreground">Original Reset: {formatEpoch(value.originalResetAt)}</p>
      <p className="text-muted-foreground">
        Effective Reset: {value.resetScheduleInvalidated ? "—" : formatEpoch(value.effectiveResetAt)}
      </p>
      {value.resetScheduleInvalidated ? (
        <p className="mt-1 text-amber-700 dark:text-amber-300">
          historical display reset schedule invalidated · 원본 증거는 보존됨
        </p>
      ) : null}
    </div>
  );
}

function WorkspaceCard({
  workspace,
  readOnly,
  busy,
  onToggle,
}: {
  workspace: RotationWorkspaceOperator;
  readOnly: boolean;
  busy: boolean;
  onToggle: (workspace: RotationWorkspaceOperator, enabled: boolean) => void;
}) {
  const hasAttention =
    workspace.blockerCodes.length > 0 ||
    workspace.foundation?.attentionRequired === true ||
    workspace.controller.status === "needs_attention" ||
    workspace.resetCredit.state === "reconciliation_pending" ||
    workspace.resetCredit.state === "unavailable" ||
    workspace.controller.companionStatus === "capability_mismatch" ||
    workspace.controller.companionStatus === "provenance_mismatch";
  const fiveHour = workspace.fiveHourUsage;
  const safeNextCandidate =
    workspace.nextCandidate && workspace.nextCandidate.email.toLowerCase() !== workspace.ownerEmail.toLowerCase()
      ? workspace.nextCandidate
      : null;
  const inviteStatus =
    workspace.controller.membershipConfirmed === true
      ? "멤버십 등록 확인됨"
      : workspace.controller.invitationIssued === true
        ? "Invite 전송됨 · 멤버십 등록은 아직 미확인"
        : null;

  return (
    <article className="space-y-4 rounded-xl border bg-card p-4" data-testid={`rotation-workspace-${workspace.workspaceId}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="font-semibold">{workspace.workspaceName}</h4>
            <Badge variant={workspace.automaticRotationEnabled ? "default" : "secondary"}>
              {workspace.automaticRotationEnabled ? "ON" : "OFF"}
            </Badge>
            {hasAttention ? <Badge variant="destructive">확인 필요</Badge> : null}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">Owner: {workspace.ownerEmail}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            이 스위치는 backend 제어 의도만 저장합니다. 이 화면에서 remove, invite, reset credit를 실행하지 않습니다.
          </p>
        </div>
        <Switch
          aria-label={`${workspace.workspaceName} 자동 멤버 교체`}
          checked={workspace.automaticRotationEnabled}
          disabled={readOnly || busy}
          onCheckedChange={(checked) => onToggle(workspace, checked)}
        />
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-lg border p-3">
          <p className="text-xs font-medium text-muted-foreground">Current member</p>
          <p className="mt-1 text-sm font-medium">{workspace.currentMember?.email ?? "미확인"}</p>
        </div>
        <div className="rounded-lg border p-3">
          <p className="text-xs font-medium text-muted-foreground">Weekly Usage state</p>
          <p className="mt-1 text-sm font-medium">{weeklyLabel(workspace)}</p>
          <p className="mt-1 text-[11px] text-muted-foreground">G1 classification을 그대로 표시합니다.</p>
        </div>
        <div className="rounded-lg border p-3">
          <p className="text-xs font-medium text-muted-foreground">5H Usage state</p>
          <p className="mt-1 text-sm font-medium">
            {fiveHour.state === "observed" ? "관측됨" : fiveHour.state === "not_provided" ? "미제공" : `미확인 · ${fiveHour.state}`}
            {fiveHour.state === "observed" && fiveHour.usedPercent != null ? ` · ${fiveHour.usedPercent.toFixed(1)}% used` : ""}
          </p>
          <p className="mt-1 text-[11px] text-muted-foreground">표시용 관측값이며 Weekly eligibility 판정에 사용하지 않습니다.</p>
        </div>
        <div className="rounded-lg border p-3">
          <p className="text-xs font-medium text-muted-foreground">Reset-credit resolution</p>
          <p className="mt-1 text-sm font-medium">{resetLabel(workspace.resetCredit.state)}</p>
          {workspace.resetCredit.detail ? (
            <p className="mt-1 break-all text-[11px] text-muted-foreground">{workspace.resetCredit.detail}</p>
          ) : null}
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <div className="rounded-lg border p-3">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4" aria-hidden="true" />
            <p className="text-sm font-medium">Internal rotation guard</p>
          </div>
          <p className="mt-2 text-sm">24H {workspace.quota.count24H} / {workspace.quota.limit24H}</p>
          <p className="text-sm">7D {workspace.quota.count168H} / {workspace.quota.limit168H}</p>
          <p className="mt-2 text-[11px] text-muted-foreground">
            내부 안전 정책입니다. OpenAI 서버 한도로 표시하지 않습니다.
          </p>
        </div>
        <div className="rounded-lg border p-3">
          <div className="flex items-center gap-2">
            <History className="h-4 w-4" aria-hidden="true" />
            <p className="text-sm font-medium">History confidence / coverage</p>
          </div>
          <p className="mt-2 text-sm">
            {workspace.quota.historyComplete ? "Coverage complete" : "Observed locally"}
          </p>
          <p className="text-xs text-muted-foreground">Coverage since: {formatDate(workspace.quota.coverageStartedAt)}</p>
          {!workspace.quota.historyComplete ? (
            <p className="mt-2 text-[11px] text-amber-700 dark:text-amber-300">
              시스템 도입 전 또는 외부 수동 member change는 포함되지 않을 수 있습니다.
            </p>
          ) : null}
        </div>
        <div className="rounded-lg border p-3">
          <p className="text-xs font-medium text-muted-foreground">Foundation / Controller</p>
          <p className="mt-1 text-sm font-medium">Foundation: {foundationLabel(workspace.foundation?.state)}</p>
          <p className="text-sm">Controller: {workspace.controller.status}</p>
          {workspace.controller.reason ? (
            <p className="mt-1 text-xs text-muted-foreground">
              Reason: {blockerLabel(workspace.controller.reason)}
            </p>
          ) : null}
          <p className="mt-2 text-xs text-muted-foreground">
            Next candidate: {safeNextCandidate?.email ?? "controller가 보고하지 않음"}
          </p>
          {inviteStatus ? <p className="mt-2 text-xs font-medium">{inviteStatus}</p> : null}
        </div>
      </div>

      {hasAttention ? (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3" role="alert">
          <div className="flex items-center gap-2 text-sm font-medium">
            <AlertTriangle className="h-4 w-4" aria-hidden="true" />
            자동 교체가 멈춘 이유를 확인하세요
          </div>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs">
            {workspace.blockerCodes.map((code) => <li key={code}>{blockerLabel(code)}</li>)}
          </ul>
          <p className="mt-2 text-[11px] text-muted-foreground">
            여기에는 remove/invite 재전송 버튼이 없습니다. effect outcome이 불명확하면 read-only reconciliation 경계를 따릅니다.
          </p>
        </div>
      ) : null}

      <div className="space-y-2">
        <p className="text-sm font-medium">Removed-member final Usage history</p>
        {workspace.history.length === 0 ? (
          <p className="text-xs text-muted-foreground">보존된 removed-member final Usage가 없습니다.</p>
        ) : (
          workspace.history.map((entry) => (
            <div key={`${entry.userId}:${entry.membershipEpoch}`} className="rounded-lg border p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-medium">{entry.email}</p>
                  <p className="text-xs text-muted-foreground">Removed at: {formatDate(entry.removedAt) || "—"}</p>
                  {!entry.removedAt ? (
                    <p className="text-[11px] text-muted-foreground">controller가 removal 시각을 아직 보고하지 않았습니다.</p>
                  ) : null}
                </div>
                <p className="text-[11px] text-muted-foreground">Final snapshot retained: {formatDate(entry.retainedAt)}</p>
              </div>
              <div className="mt-3 grid gap-2 md:grid-cols-2">
                <UsageHistoryWindow label="5H" value={entry.fiveHour} fiveHourState={entry.fiveHourState} />
                <UsageHistoryWindow label="Weekly" value={entry.weekly} />
              </div>
            </div>
          ))
        )}
      </div>
    </article>
  );
}

export function MemberRotationPanel({ readOnly }: { readOnly: boolean }) {
  const { statusQuery, intentMutation } = useMemberRotationOperator(!readOnly);
  const workspaces = statusQuery.data?.workspaces ?? [];

  if (readOnly) {
    return (
      <section className="space-y-3 rounded-xl border bg-card/50 p-4" data-testid="member-rotation-operator-panel">
        <div>
          <h3 className="text-base font-semibold">자동 멤버 교체 · Operator 상태</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            멤버·Owner 상태를 보려면 accounts:write 권한이 필요합니다.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="space-y-3 rounded-xl border bg-card/50 p-4" data-testid="member-rotation-operator-panel">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold">자동 멤버 교체 · Operator 상태</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            페이지 로드, focus, route 이동, reconnect, polling은 교체 실행 권한이 아닙니다. 이 영역은 상태 관찰과 ON/OFF 의도 저장만 담당합니다.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={statusQuery.isFetching}
          onClick={() => void statusQuery.refetch()}
        >
          <RefreshCw className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
          상태 새로고침
        </Button>
      </div>

      {statusQuery.isLoading ? <p className="text-sm text-muted-foreground">rotation 상태를 불러오는 중…</p> : null}
      {statusQuery.error ? (
        <p role="alert" className="text-sm text-destructive">rotation operator 상태를 불러오지 못했습니다.</p>
      ) : null}
      {!statusQuery.isLoading && !statusQuery.error && workspaces.length === 0 ? (
        <p className="text-sm text-muted-foreground">구성된 Business workspace가 없습니다.</p>
      ) : null}
      {workspaces.map((workspace) => (
        <WorkspaceCard
          key={workspace.workspaceId}
          workspace={workspace}
          readOnly={readOnly}
          busy={intentMutation.isPending}
          onToggle={(target, enabled) =>
            intentMutation.mutate({
              workspaceId: target.workspaceId,
              enabled,
              expectedVersion: target.controlVersion,
            })
          }
        />
      ))}
    </section>
  );
}
