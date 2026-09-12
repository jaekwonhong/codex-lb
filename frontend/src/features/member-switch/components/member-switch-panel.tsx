import { useState } from "react";
import { AlertMessage } from "@/components/alert-message";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useMemberSwitch } from "@/features/member-switch/hooks/use-member-switch";
import { membershipObservationConfirmed, type AuthEnrollmentAction, type AuthEnrollmentView, type RunAction, type RunView } from "@/features/member-switch/run-client";

const ACTIONS: Record<RunAction, { label: string; confirm?: string }> = {
  start: { label: "교체 요청 1회", confirm: "표시된 기존 멤버를 제거하고 대상 멤버를 초대합니다. 인증 전환은 별도 단계입니다." },
  observe_membership: { label: "멤버 상태 확인" },
  prepare_session: { label: "Ego Lite 로그인 확인", confirm: "대상 멤버의 ID 전용 Ego Lite 프로필에서 ChatGPT 로그인 ID를 확인합니다. 미로그인 상태라면 해당 프로필의 로그인 화면만 열며, 기존 CDP나 시스템 기본 브라우저로 대체하지 않습니다. 이미 발급된 인증 작업과 장치 코드는 유지합니다." },
  prepare_auth: { label: "인증 준비", confirm: "준비된 세션을 바탕으로 기존 auth를 라우팅에서 격리한 뒤 장치 코드를 발급합니다. 아직 기존 auth를 삭제하지 않습니다." },
  open_browser: { label: "ID 전용 Ego Lite 열기", confirm: "대상 멤버와 로그인 ID가 일치하는 Ego Lite 프로필에서만 인증 페이지를 열어 사용자에게 제어권을 넘깁니다. 인증 코드는 클립보드에 준비됩니다." },
  observe_auth: { label: "인증 상태 읽기" },
  advance_auth: { label: "인증 진행·반영", confirm: "OAuth 상태를 확인하고 인증이 검증되면 기존 auth를 삭제합니다. 장치 코드가 만료되었다면 재발급할 수 있습니다. 단순 조회가 아닙니다." },
  close_browser: { label: "Ego Lite 종료", confirm: "이 작업에 속한 ID 전용 Ego Lite Task Space만 닫습니다. 프로필의 로그인 상태는 유지하며, 인증 완료나 작업 잠금 해제를 뜻하지 않습니다." },
  finish: { label: "종료 확인", confirm: "Companion의 작업 종료를 확인하고 서버의 전역 작업 잠금을 해제합니다. 멤버 변경을 되돌리지 않습니다." },
  cancel: { label: "미리보기 취소" },
  reconcile: { label: "저장된 실행 결과 확인" },
};
const RECOVERY_HINTS: Record<string, string> = {
  preview_expired: "미리보기가 만료되었습니다. 서버 기록을 새로고침한 뒤 미리보기를 취소하고 대상을 다시 선택하세요. 같은 교체 요청을 반복하지 마세요.",
  revision_conflict: "다른 요청에서 작업이 갱신되었습니다. 서버 기록을 새로고침하고 현재 단계와 대상을 다시 확인하세요.",
  catalog_identity_mismatch: "후보 목록이 변경되었습니다. 아직 멤버 교체 전이라면 서버 기록을 확인해 미리보기를 취소한 뒤 목록을 다시 불러오세요.",
  command_response_timeout: "응답 대기 시간이 지났습니다. 서버 작업이 취소되었다는 뜻은 아닙니다. 서버 기록을 새로고침해 결과를 확인하세요.",
  status_request_timeout: "서버 기록 조회 시간이 지났습니다. 연결을 확인한 뒤 서버 기록 새로고침을 다시 눌러 주세요.",
  participant_outcome_still_unknown: "저장된 완료 결과가 아직 없습니다. 작업 ID와 잠금을 유지하고 변경 명령을 반복하지 마세요. 잠시 후 저장된 실행 결과를 다시 확인할 수 있습니다.",
  start_outcome_still_unknown: "멤버 교체의 접수 여부를 아직 확정할 수 없습니다. 같은 교체를 다시 시작하거나 작업 기록을 지우지 마세요.",
  browser_runtime_binding_unavailable: "이 브라우저의 실행 소유권을 현재 Companion에서 확인할 수 없습니다. 다시 열거나 강제로 종료하지 말고 작업 식별자를 보존해 운영자 확인을 받으세요.",
  member_auth_already_active: "선택한 현재 멤버의 OAuth가 이미 활성 상태입니다. 목록을 새로고침해 현재 OAuth 상태를 다시 확인하세요.",
  oauth_enrollment_member_not_current: "선택한 멤버가 더 이상 실제 워크스페이스 멤버로 확인되지 않습니다. 목록을 새로고침해 실제 멤버를 다시 확인하세요.",
  member_auth_identity_ambiguous: "같은 워크스페이스의 로컬 OAuth 신원을 하나로 확정할 수 없습니다. 자동으로 덮어쓰지 않았습니다. 계정 목록과 OAuth 상태를 먼저 정리하세요.",
  member_auth_quarantined: "선택한 멤버의 auth가 기존 handoff 격리 상태입니다. 새 OAuth를 덮어쓰지 말고 기존 작업 기록을 먼저 확인하세요.",
  auth_enrollment_retained: "완료되지 않은 OAuth-only 작업이 남아 있습니다. 서버 기록 새로고침으로 해당 작업을 복원한 뒤 이어서 처리하세요.",
  device_code_expired_requires_new_enrollment: "장치 코드가 만료되었습니다. 이 작업을 종료한 뒤 목록을 다시 확인하고 OAuth 등록을 새로 시작하세요. 만료된 코드는 자동 재발급하지 않습니다.",
  ego_browser_unavailable: "Mac에서 Ego Lite 실행 도구를 찾을 수 없습니다. 기본 브라우저로 대체하지 않았습니다.",
  ego_profile_not_found: "이 멤버에 할당된 Ego Lite 프로필이 아직 없습니다. 프로필을 준비한 뒤 같은 장치 코드가 유효하면 다시 시도하세요.",
  ego_profile_login_required: "이 ID의 Ego Lite 프로필에 ChatGPT 로그인이 필요합니다. 열린 Ego Lite 창에서 표시된 ID로 로그인한 뒤 「Ego Lite 로그인 확인」을 다시 실행하세요. 확인 시 해당 Task Space의 제어권을 잠시 회수해 로그인 ID를 검증합니다.",
  ego_member_session_not_prepared: "이 ID의 Ego Lite 작업 창을 다시 준비해야 합니다. 「Ego Lite 로그인 확인」 후 「ID 전용 Ego Lite 열기」를 실행하세요. 기존 인증 작업과 장치 코드는 유지됩니다.",
  ego_member_session_ready: "이 ID의 Ego Lite 프로필 로그인 상태가 확인되었습니다.",
  ego_task_space_user_controlled: "해당 Ego Lite 창을 사용자가 제어 중입니다. 필요한 작업을 마친 뒤 Ego Lite에서 제어권을 AI에 반환하고 계속하세요.",
  ego_task_space_ownership_mismatch: "해당 Ego Lite Task Space의 제어권 상태가 예상과 달라 자동으로 가져오지 않았습니다. 기존 창의 제어권 상태를 확인하세요.",
  ego_task_space_takeover_failed: "로그인 확인을 위해 사용자 제어 중인 Ego Lite Task Space를 회수했지만 결과를 확정하지 못했습니다. 같은 확인을 반복하기 전에 현재 Ego Lite 창 상태와 서버 기록을 확인하세요.",
  ego_task_space_takeover_unconfirmed: "Ego Lite가 제어권 회수 요청을 처리했지만 실제 agent 제어 상태를 재확인하지 못했습니다. 같은 확인을 반복하지 말고 서버 기록을 확인하세요.",
  ego_browser_identity_unavailable: "로그인 상태 조회에 실패했습니다. 로그아웃되었다는 뜻은 아닙니다. 「Ego Lite 로그인 확인」으로 다시 확인하세요. 다른 브라우저로 대체하지 않았습니다.",
  ego_browser_unsafe_location: "로그인 ID 확인 중 허용되지 않은 페이지로 이동해 작업을 중단했습니다. 다른 브라우저로 대체하지 않았습니다.",
  ego_task_space_close_failed: "Ego Lite Task Space 종료 결과를 확정하지 못했습니다. 같은 종료 요청을 반복하기 전에 현재 창 상태를 확인하세요.",
  ego_task_space_close_unconfirmed: "Ego Lite가 종료 요청을 처리했지만 Task Space가 사라졌는지 재확인하지 못했습니다. 「저장된 실행 결과 확인」으로 정확한 창의 종료 여부를 확인하세요. 종료 명령은 반복하지 않습니다.",
  ego_browser_identity_mismatch: "현재 멤버와 Ego Lite 프로필의 로그인 ID가 일치하지 않습니다. 열린 Ego Lite 창에서 올바른 ID로 전환한 뒤 「Ego Lite 로그인 확인」을 다시 실행하세요. 다른 브라우저로 대체하지 않았습니다.",
  ego_browser_account_mapping_unavailable: "현재 preset을 stable account ID 하나로 확정할 수 없습니다. 다른 브라우저를 열지 않았습니다.",
  ego_owner_account_mapping_unavailable: "워크스페이스 소유주 이메일을 managed account 하나로 확정할 수 없어 목록 조회를 중단했습니다. 기존 CDP로 대체하지 않았습니다.",
  ego_owner_profile_login_required: "이 워크스페이스 소유주 ID의 Ego Lite 프로필에 ChatGPT 로그인이 필요합니다. 열린 소유주 Space에서 표시된 이메일로 로그인한 뒤 목록 새로고침을 다시 실행하세요.",
  ego_owner_identity_mismatch: "워크스페이스 소유주 Ego Lite 프로필의 로그인 이메일이 기대한 소유주 ID와 다릅니다. 열린 소유주 Space에서 올바른 ID로 전환한 뒤 목록 새로고침을 다시 실행하세요.",
  ego_owner_identity_unavailable: "워크스페이스 소유주 Ego Lite 로그인 상태를 확인하지 못했습니다. 로그아웃으로 단정하거나 기존 CDP로 대체하지 않았습니다.",
  ego_owner_task_space_identity_unavailable: "소유주 Ego Lite Space의 정확한 식별 정보를 확인할 수 없어 목록 조회를 중단했습니다. 다른 Space나 CDP를 대신 사용하지 않았습니다.",
  ego_owner_membership_response_invalid: "소유주 Ego Lite에서 받은 멤버 목록 응답을 안전하게 해석할 수 없어 결과를 사용하지 않았습니다.",
  ego_owner_personal_outcome_unknown: "소유주 Ego Lite의 개인 계정 전환 결과를 확정할 수 없습니다. 멤버 변경 명령을 반복하지 말고 현재 작업 기록을 확인하세요.",
  ego_owner_task_space_close_unconfirmed: "소유주 Ego Lite Space 종료 결과를 확정하지 못했습니다. 다른 Space나 CDP를 대신 닫지 않았습니다.",
  delete_outcome_unknown: "소유주 Ego Lite에서 멤버 삭제 응답을 확정하지 못했습니다. 같은 삭제를 반복하지 않고 실제 멤버 목록으로 결과를 확인합니다.",
  invite_outcome_unknown: "소유주 Ego Lite에서 초대 응답을 확정하지 못했습니다. 같은 초대를 반복하지 않고 실제 멤버·초대 목록으로 결과를 확인합니다.",
  invite_cancel_outcome_unknown: "소유주 Ego Lite에서 초대 취소 응답을 확정하지 못했습니다. 취소를 반복하지 않고 실제 초대 목록으로 결과를 확인합니다.",
  ego_recipient_profile_login_required: "대상 ID의 Ego Lite 프로필에 ChatGPT 로그인이 필요합니다. 열린 수신자 Space에서 정확한 ID로 로그인한 뒤 현재 단계를 다시 확인하세요. CDP로 대체하지 않습니다.",
  ego_recipient_identity_mismatch: "수신자 Ego Lite 프로필의 로그인 이메일 또는 사용자 ID가 선택한 멤버와 일치하지 않습니다. 해당 Space에서 정확한 계정을 확인하세요.",
  ego_recipient_identity_unavailable: "수신자 Ego Lite 로그인 ID를 확정하지 못했습니다. 로그아웃으로 단정하거나 CDP로 대체하지 않았습니다.",
  ego_recipient_task_space_creation_unconfirmed: "수신자 Ego Lite Space 생성 결과와 profile authority를 재확인하지 못했습니다. 다른 Space를 대신 사용하지 않았습니다.",
  ego_recipient_task_space_identity_unavailable: "수신자 Ego Lite Space의 정확한 profile/Task Space ID를 확인하지 못해 작업을 중단했습니다.",
  ego_recipient_personal_outcome_unknown: "수신자 Ego Lite의 Personal 전환 결과를 확정하지 못했습니다. 멤버십 효과를 반복하지 말고 저장된 실행 상태를 확인하세요.",
  ego_recipient_task_space_close_unconfirmed: "수신자 Ego Lite Space 종료 여부를 확정하지 못했습니다. 다른 Space를 대신 닫지 않았습니다.",
  acceptance_session_unavailable: "수신자 세션의 현재 계정 정보를 확인하지 못해 초대 수락 요청을 보내지 않았습니다. 로그인 상태와 저장된 작업 결과를 확인하세요.",
  acceptance_outcome_unknown: "수신자 Ego Lite에서 초대 수락 요청 결과를 확정하지 못했습니다. 같은 수락 요청을 반복하지 않고 owner 멤버십과 recipient workspace 관찰로 결과를 확인합니다.",
  recipient_workspace_observation_unavailable: "수신자 Ego Lite에서 워크스페이스 상태를 확정하지 못했습니다. CDP로 대체하지 않고 현재 상태를 보존합니다.",
  ego_task_space_profile_mismatch: "같은 OAuth 작업 이름의 Ego Lite Task Space가 다른 프로필에 연결되어 있습니다. 자동으로 takeover하거나 교체하지 않았습니다.",
  ego_task_space_ambiguous: "같은 OAuth 작업 이름의 Ego Lite Task Space가 여러 개 있어 하나로 확정할 수 없습니다. 자동 선택하지 않았습니다.",
  ego_task_space_not_handed_off: "Ego Lite Task Space가 존재하지만 사용자 제어권 전달 여부를 확정하지 못했습니다. 저장된 실행 결과 확인을 사용하세요.",
  ego_task_space_handoff_failed: "Ego Lite 인증 창을 준비했지만 사용자 제어권 전달 결과를 확정하지 못했습니다. 같은 명령을 반복하지 말고 저장된 실행 결과를 확인하세요.",
  ego_task_space_handoff_unconfirmed: "Ego Lite가 handoff 성공을 응답했지만 실제 Task Space의 사용자 제어 상태를 재확인하지 못했습니다. 같은 명령을 반복하지 마세요.",
  ego_browser_account_id_invalid: "관리 account ID가 Ego Lite 프로필 신원 규칙과 맞지 않아 브라우저를 열지 않았습니다.",
  ego_task_space_identity_unavailable: "정확한 Ego Lite 창 식별 정보를 확인할 수 없습니다. 기존 기록을 보존하고 운영자 확인을 받으세요. 다른 창을 대신 닫지 않았습니다.",
  ego_browser_timeout: "Ego Lite 응답 대기 시간이 지났습니다. 브라우저가 열리지 않았다고 단정하지 말고 저장된 실행 결과를 확인하세요.",
  ego_browser_response_invalid: "Ego Lite 응답이 불완전해 실행 결과를 확정하지 못했습니다. 작업 기록을 보존한 채 서버 기록과 저장된 실행 결과를 확인하고, 같은 브라우저 명령을 반복하지 마세요.",
  ego_owner_mutation_response_invalid: "소유주 Ego Lite의 변경 결과를 해석하지 못했습니다. 같은 삭제·초대·취소를 반복하지 말고 저장된 작업과 멤버 상태를 확인하세요.",
  oauth_pending: "OAuth 서버 확인이 아직 진행 중입니다. 자동 확인 상한에 도달한 경우 현재 작업을 유지하고 「남은 OAuth 절차 자동 진행」으로 서버 상태 확인만 이어가세요. Ego Lite 장치코드를 다시 제출하지 않습니다.",
  ego_device_auth_user_action_required: "Ego Lite가 정확한 계정·워크스페이스·장치코드 자동화를 안전하게 계속할 수 없어 같은 멤버 Space를 사용자에게 넘겼습니다. 비밀번호·MFA·보안 확인 또는 모호한 선택을 직접 완료한 뒤 「인증 확인·반영」을 사용하세요. 다른 브라우저로 대체하지 않습니다.",
  ego_device_auth_code_submitted: "Ego Lite가 장치코드를 정확히 한 번 제출했지만 완료 화면을 확정하지 못했습니다. 같은 코드를 다시 제출하지 말고 현재 Space의 상태를 확인한 뒤 「인증 확인·반영」을 사용하세요.",
  ego_device_auth_code_submission_unconfirmed: "장치코드 제출 단계에서 페이지 응답을 확인하지 못했습니다. 동일 코드를 자동 재제출하지 않았습니다. 현재 Ego Lite Space를 확인한 뒤 「인증 확인·반영」으로 서버 OAuth 상태를 조회하세요.",
  ego_browser_process_failed: "Ego Lite 실행 결과를 확정하지 못했습니다. 기본 브라우저로 대체하지 않았습니다.",
};
function recoveryHint(code: string, flow: RunView | null = null): string | undefined {
  if (flow && flow.phase !== "completed" && [
    "ego_owner_profile_login_required", "ego_owner_identity_mismatch", "ego_owner_identity_unavailable",
  ].includes(code)) {
    if (flow.allowedActions.includes("reconcile"))
      return "현재 요청의 완료 여부를 아직 확정하지 못했습니다. 「저장된 실행 결과 확인」으로 현재 요청의 결과를 확인하세요. 같은 변경 요청을 반복하지 않으며 로그인 창도 자동으로 가져오지 않습니다.";
    if (!flow.allowedActions.includes("finish") && !flow.allowedActions.includes("observe_membership"))
      return "서버 작업 기록을 다시 확인하세요. 현재 허용된 복구 동작이 없으면 작업 식별자를 보존해 운영자 검토를 받으세요. 같은 변경을 반복하지 마세요.";
    return flow.allowedActions.includes("finish")
      ? "소유주 Ego Lite의 로그인 상태를 확인하세요. 멤버 변경 전 실패로 확인된 작업입니다. 「종료 확인」으로 현재 작업을 종료한 뒤 목록을 새로고침하세요. 로그인 창은 자동으로 가져오거나 닫지 않습니다."
      : "소유주 Ego Lite의 로그인 상태와 서버 작업 기록을 확인하세요. 종료가 허용되지 않은 상태이므로 「서버 기록 새로고침」과 「멤버 상태 확인」으로 결과를 확인하고, 미확정 상태가 계속되면 작업 식별자를 보존해 운영자 검토를 받으세요. 같은 교체를 반복하지 마세요.";
  }
  return RECOVERY_HINTS[code];
}

const PHASES: Record<string, string> = {
  previewed: "교체 대상 확인", membership_requested: "멤버 교체 요청됨", membership_confirmed: "멤버 등록 확인됨",
  session_prepared: "로그인 세션 준비됨", auth_prepared: "인증 준비됨", auth_browser_opened: "인증 브라우저 열림", auth_confirmed: "인증 완료 확인됨",
  completed: "작업 종료 확인됨", needs_attention: "별도 확인 필요", failed: "실패", outcome_unknown: "실행 결과 미확정",
};
const AUTH_ACTIONS: Record<AuthEnrollmentAction, { label: string; confirm?: string }> = {
  prepare_auth: { label: "장치 코드 발급" },
  open_auth_browser: { label: "Ego Lite 인증 브라우저 열기" },
  advance_auth: {
    label: "인증 확인·반영",
    confirm: "장치 코드 OAuth 상태를 확인하고 정확한 이메일·사용자 ID·워크스페이스가 일치하는 경우에만 auth를 등록합니다. 만료된 장치 코드는 자동 재발급하지 않으며 현재 작업을 종료한 뒤 새 OAuth 등록을 시작해야 합니다.",
  },
  finish: {
    label: "OAuth 작업 종료 확인",
    confirm: "현재 OAuth 결과와 증거를 보존한 채 이 OAuth-only 작업의 전역 잠금을 해제합니다. 멤버십은 변경하지 않습니다.",
  },
  cancel: { label: "OAuth 준비 취소" },
  reconcile: { label: "저장된 OAuth 실행 결과 확인" },
};
const AUTH_PHASES: Record<string, string> = {
  prepared: "OAuth 등록 대상 확인",
  auth_prepared: "장치 코드 발급됨",
  auth_browser_opened: "Ego Lite 인증 브라우저 열림",
  auth_confirmed: "OAuth 등록 확인됨",
  completed: "OAuth 작업 종료 확인됨",
  needs_attention: "OAuth 별도 확인 필요",
  outcome_unknown: "OAuth 실행 결과 미확정",
};
const AUTH_STATE_LABELS: Record<string, string> = {
  active: "OAuth 등록됨",
  absent: "OAuth 미등록",
  inactive: "OAuth 재등록 필요",
  handoff_quarantined: "OAuth 격리 상태",
  ambiguous: "OAuth 신원 확인 필요",
  unmanaged: "관리 후보 아님",
  unknown: "OAuth 상태 미확인",
};

function oauthAutoProgressLabel(progress: AuthEnrollmentView | null): string {
  if (!progress) return "OAuth 등록 대상 확인 중";
  if (progress.pendingAction === "prepare_auth") return "장치 코드 발급 중";
  if (progress.pendingAction === "open_auth_browser") return "장치 코드 발급 완료 · Ego Lite 인증 시작 중";
  if (progress.pendingAction === "advance_auth") return "장치 코드 제출 완료 · OAuth 서버 확인 중";
  if (progress.pendingAction === "finish") return "OAuth 등록 확인됨 · 작업 정리 중";
  if (progress.pendingAction === "reconcile") return "저장된 OAuth 실행 결과 확인 중";
  if (progress.phase === "prepared") return "OAuth 등록 대상 확인 · 장치 코드 발급 준비 중";
  if (progress.phase === "auth_prepared") return "장치 코드 발급 완료 · Ego Lite 인증 시작 중";
  if (progress.phase === "auth_browser_opened") {
    return progress.authState === "oauth_pending" || progress.lastCode === "oauth_pending"
      ? "장치 코드 제출 완료 · OAuth 서버 확인 중"
      : "Ego Lite 인증 진행 중";
  }
  if (progress.phase === "auth_confirmed") return "OAuth 등록 확인됨 · 작업 정리 중";
  if (progress.phase === "completed") return "OAuth 등록 완료";
  if (progress.phase === "needs_attention") return "OAuth 별도 확인 필요";
  return "OAuth 실행 결과 확인 중";
}

export function MemberSwitchPanel({ readOnly }: { readOnly: boolean }) {
  const runtime = useMemberSwitch(readOnly);
  const { flow, enrollment, catalog, error, busy, checked, legacy } = runtime;
  const [confirmation, setConfirmation] = useState<{ action: RunAction; id: string; revision: number } | null>(null);
  const [authConfirmation, setAuthConfirmation] = useState<{ action: AuthEnrollmentAction; id: string; revision: number } | null>(null);
  const disabled = readOnly || busy !== null;
  const catalogRefreshDisabled = disabled || !checked || Boolean(flow && flow.phase !== "completed") || Boolean(enrollment && enrollment.phase !== "completed");
  const confirmedFlow = confirmation && flow?.id === confirmation.id && flow.revision === confirmation.revision;
  const confirmedEnrollment = authConfirmation && enrollment?.id === authConfirmation.id && enrollment.revision === authConfirmation.revision;
  const probeHttpStatus = runtime.oauthProbe?.result?.probeStatusCode ?? null;
  const probeSucceeded = probeHttpStatus !== null && probeHttpStatus >= 200 && probeHttpStatus < 300;
  return <section aria-labelledby="member-switch-title" className="rounded-xl border bg-card p-4 sm:p-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h2 id="member-switch-title" className="text-sm font-semibold">멤버 관리 · 전환 / OAuth 등록</h2>
        <p className="mt-1 max-w-3xl text-xs leading-5 text-muted-foreground">
          멤버 교체는 대상 확인 → 교체 → 인증 전환 → 종료 확인 순서로 직접 승인합니다.
          이미 현재 멤버인 계정은 「OAuth 등록」 한 번으로 장치코드 발급 → Ego Lite 자동 인증 → 서버 인증 확인·반영 → 완료 정리까지 진행합니다. 멤버십은 변경하지 않습니다.
          서버 기록 새로고침은 저장 상태만 읽고, 목록 불러오기·새로고침은 각 워크스페이스 소유주 ID의 Ego Lite 프로필/Space에서 실제 멤버를 확인합니다.
          소유주 멤버 삭제·초대·초대취소와 그 전후 개인 계정 확인도 동일한 소유주 Ego Lite Space에서 수행하며, 기존 owner CDP를 대체 경로로 사용하지 않습니다.
          수신자의 Personal 확인, 워크스페이스 존재·부재 확인, 초대 수락도 해당 ID의 Ego Lite 프로필/Space에서 수행하며 managed 멤버 전환 중에는 recipient CDP로 fallback하지 않습니다.
          확인된 이메일의 사용자 ID가 바뀐 경우 관리 중인 동일 계정의 ID만 갱신합니다.
          자동 순환·자동 복구는 실행하지 않습니다.
        </p></div>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" disabled={readOnly || (busy !== null && busy !== "restore")} onClick={() => void runtime.refresh()}>서버 기록 새로고침</Button>
        <Button size="sm" variant="outline" disabled={catalogRefreshDisabled} onClick={() => void runtime.loadCatalog()}>
          {catalog ? "목록 새로고침" : "목록 불러오기"}
        </Button>
      </div>
    </div>
    {readOnly ? <p className="mt-4 text-sm">관리자만 멤버 전환과 OAuth 등록을 조회·실행할 수 있습니다.</p> : null}
    {busy ? <p role="status" className="mt-4 flex items-center gap-2 text-sm"><Spinner size="sm" />
      {busy === "oauth_enrollment_auto"
        ? oauthAutoProgressLabel(runtime.autoProgress)
        : busy === "oauth_probe"
          ? "OAuth 등록 완료 · 강제 Probe로 연결·토큰 확인 중"
          : `${ACTIONS[busy as RunAction]?.label ?? AUTH_ACTIONS[busy.replace(/^oauth_/, "") as AuthEnrollmentAction]?.label ?? "서버 조회"} · 응답 대기 중`}
    </p> : null}
    {runtime.oauthProbe?.result ? <AlertMessage className="mt-4" variant={probeSucceeded ? "success" : "warning"}>
      {probeSucceeded
        ? `강제 Probe 완료 · 연결 정상 · 토큰 사용 가능 · HTTP ${probeHttpStatus} · 계정 상태 ${runtime.oauthProbe.result.accountStatusAfter}`
        : `OAuth 등록은 완료됨 · 강제 Probe 연결 확인 실패 · HTTP ${probeHttpStatus ?? "미확인"} · 계정 상태 ${runtime.oauthProbe.result.accountStatusAfter}`}
    </AlertMessage> : runtime.oauthProbe?.errorCode ? <AlertMessage className="mt-4" variant="warning">
      {runtime.oauthProbe.errorCode === "account_probe_refresh_failed"
        ? "OAuth 등록은 완료됐습니다. 강제 Probe에서 토큰 갱신에 실패했습니다."
        : runtime.oauthProbe.errorCode === "oauth_probe_account_unresolved"
          ? "OAuth 등록은 완료됐지만 강제 Probe 대상 auth 계정을 하나로 확인하지 못했습니다."
          : runtime.oauthProbe.errorCode === "oauth_probe_timeout"
            ? "OAuth 등록은 완료됐습니다. 강제 Probe 응답 시간이 초과되어 연결 상태를 확정하지 못했습니다."
            : "OAuth 등록은 완료됐지만 강제 Probe 연결·토큰 확인을 완료하지 못했습니다."}
      <code className="mt-1 block break-all text-xs">{runtime.oauthProbe.errorCode}</code>
    </AlertMessage> : null}
    {legacy ? <AlertMessage className="mt-4" variant="warning">이전 버전의 작업 기록이 있습니다. 새 교체를 시작하기 전 별도 복구 검토가 필요합니다. 기존 기록은 삭제하지 않았습니다.</AlertMessage> : null}
    {error ? <div className="mt-4" role="alert"><AlertMessage variant="error">
      {recoveryHint(error, flow) ?? "요청을 완료하지 못했습니다. 변경 요청은 재전송하지 않았습니다. 서버 기록을 새로고침해 결과를 확인하세요."}
      <code className="mt-1 block break-all text-xs">{error}</code>
    </AlertMessage></div> : null}
    {!checked && !readOnly ? <p className="mt-4 text-xs text-muted-foreground">서버 작업 기록을 확인하기 전에는 다음 변경을 실행하지 않습니다.</p> : null}
    {catalog && !catalog.enabled ? <AlertMessage className="mt-4" variant="warning">Companion 비활성화</AlertMessage> : null}
    {catalog?.enabled ? <div className="mt-4 grid gap-3 lg:grid-cols-2">{catalog.workspaces.map((workspace) =>
      <section key={workspace.id} className="min-w-0 rounded-lg border p-3">
        <h3 className="break-words text-sm font-medium">{workspace.workspaceName}</h3>
        <p className="mt-1 break-all text-xs text-muted-foreground">소유주: {workspace.ownerEmail}</p>
        {workspace.membershipCode === "not_checked" ? <p className="mt-1 text-xs text-muted-foreground">멤버: 목록 새로고침 필요</p>
          : workspace.currentMembers.length > 0 ? <div className="mt-2 space-y-2">{workspace.currentMembers.map((member) => {
            const canEnroll = membershipObservationConfirmed(workspace) && Boolean(member.presetId) && ["absent", "inactive"].includes(member.authState)
              && !disabled && checked && !legacy && !(flow && flow.phase !== "completed") && !(enrollment && enrollment.phase !== "completed");
            return <div key={`${member.email}:${member.userId}`} className="rounded-md border bg-muted/20 px-2.5 py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="break-all text-xs text-muted-foreground">멤버: {member.email}</p>
                  <p className="mt-0.5 text-xs">{AUTH_STATE_LABELS[member.authState] ?? member.authState}</p>
                </div>
                {canEnroll ? <Button size="sm" variant="outline" onClick={() =>
                  void runtime.startAuthEnrollment(workspace.id, member.presetId!, member.email, member.userId)}>
                  {member.authState === "inactive" ? "OAuth 다시 등록" : "OAuth 등록"}
                </Button> : null}
              </div>
              {member.authAccountId ? <code className="mt-1 block break-all text-[11px] text-muted-foreground">auth: {member.authAccountId}</code> : null}
            </div>;
          })}</div>
          : <p className="mt-1 text-xs text-muted-foreground">멤버: {["ok", "confirmed_by_operation"].includes(workspace.membershipCode) ? "없음" : "확인 실패"}</p>}
        {!membershipObservationConfirmed(workspace) && workspace.membershipCode !== "not_checked" ?
          <AlertMessage variant="warning" className="mt-2">
            {RECOVERY_HINTS[workspace.membershipCode] ?? "이 워크스페이스의 현재 멤버를 확인하지 못했습니다. 소유주 Ego Lite와 연결 상태를 확인한 뒤 목록을 새로고침하세요. 확인 전에는 교체·OAuth 등록을 시작하지 않습니다."}
            <code className="mt-1 block break-all text-xs">멤버 확인 상태: {workspace.membershipCode}</code>
          </AlertMessage> : null}
        <p className="mt-3 text-xs font-medium text-muted-foreground">전환 후보</p>
        <div className="mt-2 grid gap-2">{workspace.members.map((member) =>
          <Button key={member.presetId} variant="outline" className="h-auto min-w-0 justify-start whitespace-normal text-left"
            disabled={disabled || !checked || !membershipObservationConfirmed(workspace) || legacy || Boolean(flow && flow.phase !== "completed") || Boolean(enrollment && enrollment.phase !== "completed")}
            onClick={() => void runtime.preview(workspace.id, member.presetId)}>
            <span className="min-w-0"><span className="block break-words">{member.displayName}</span>
              <span className="block break-all text-xs font-normal">{member.email}</span></span>
          </Button>)}</div>
      </section>)}</div> : null}
    {flow ? <div className="mt-4 rounded-lg border bg-muted/20 p-3" aria-live="polite">
      <h3 className="text-sm font-semibold">{PHASES[flow.phase]}</h3>
      <p className="mt-1 break-all text-xs">{flow.identity.workspaceId} · {flow.identity.targetEmail}</p>
      {flow.pendingAction ? <AlertMessage variant="warning" className="mt-3">
        응답 유실 또는 실행 중인 요청입니다. 작업 ID와 잠금을 보존합니다. 저장된 실행 결과 확인은 멤버·OAuth·브라우저 변경을 재실행하지 않으며, 이미 저장된 종료 의도가 있으면 Companion의 로컬 작업 잠금 해제만 완료할 수 있습니다.
      </AlertMessage> : null}
      {flow.lastCode === "auth_browser_code_changed" ? <AlertMessage variant="warning" className="mt-3">
        인증 코드가 재발급되었습니다. 이 작업의 기존 인증 브라우저를 종료한 뒤 다시 열어 새 코드를 사용하세요. 멤버 교체는 반복하지 않습니다.
      </AlertMessage> : null}
      {!error && recoveryHint(flow.lastCode, flow) ? <AlertMessage variant="warning" className="mt-3">{recoveryHint(flow.lastCode, flow)}</AlertMessage> : null}
      {flow.phase === "needs_attention" ? <p className="mt-3 text-xs text-destructive">
        실패가 변경 취소를 뜻하지는 않습니다. 작업과 잠금을 유지하며, 확인된 상태 없이 새 교체나 강제 종료를 하지 않습니다.
      </p> : null}
      {flow.phase === "needs_attention" && flow.allowedActions.includes("finish") ? <AlertMessage variant="warning" className="mt-3">
        서버 기록상 멤버 변경 동작이 시작되기 전에 확정 실패한 작업입니다. 「종료 확인」은 멤버를 다시 변경하지 않고 보존된 작업 소유권만 정상 종료합니다.
      </AlertMessage> : null}
      <dl className="mt-3 grid grid-cols-[6rem_minmax(0,1fr)] gap-2 text-xs">
        <dt>제거 대상</dt><dd className="break-all">{flow.removedEmail ?? "없음"}</dd>
        <dt>멤버 교체</dt><dd className="break-all">{flow.operation ? `${flow.operation.stage} · ${flow.operation.code}` : "미확인"}</dd>
        <dt>인증 전환</dt><dd>{flow.authState ?? "아직 준비하지 않음"}</dd>
        <dt>서버 결과</dt><dd className="break-all font-mono">{flow.lastCode}</dd>
        <dt>마지막 기록</dt><dd className="break-all">{flow.updatedAt} · revision {flow.revision}</dd>
      </dl>
      {flow.phase === "membership_confirmed" ? <p className="mt-3 text-xs">멤버 등록 완료는 auth 전환 완료가 아닙니다. 다음 단계에서 인증을 준비해 주세요.</p> : null}
      <div className="mt-3 flex flex-wrap gap-2">{flow.allowedActions.map((action) =>
        <Button key={action} size="sm" variant="outline" disabled={disabled || !checked}
          onClick={() => ACTIONS[action].confirm
            ? setConfirmation({ action, id: flow.id, revision: flow.revision }) : void runtime.command(action)}>
          {ACTIONS[action].label}
        </Button>)}
        {flow.phase === "completed" ? <Button size="sm" disabled={disabled || !checked} onClick={runtime.dismissFinished}>완료 기록 닫기</Button> : null}
      </div>
      <details className="mt-3 text-xs text-muted-foreground"><summary>작업 식별자</summary>
        <pre className="mt-2 whitespace-pre-wrap break-all">{JSON.stringify({ runId: flow.id, operationId: flow.operationId,
          handoffId: flow.handoffId, browserOperationId: flow.browserOperationId, pendingAction: flow.pendingAction }, null, 2)}</pre>
      </details>
    </div> : null}
    {enrollment ? <div className="mt-4 rounded-lg border bg-muted/20 p-3" aria-live="polite">
      <h3 className="text-sm font-semibold">현재 멤버 OAuth 등록 · {AUTH_PHASES[enrollment.phase] ?? enrollment.phase}</h3>
      <p className="mt-1 break-all text-xs">{enrollment.identity.workspaceId} · {enrollment.identity.targetEmail}</p>
      <p className="mt-2 text-xs text-muted-foreground">이 경로는 워크스페이스 멤버를 제거·초대·교체하지 않으며 다른 멤버의 auth를 격리·삭제하지 않습니다.</p>
      {enrollment.pendingAction ? <AlertMessage variant="warning" className="mt-3">
        OAuth 명령 결과가 아직 확정되지 않았습니다. 동일 명령을 반복하지 말고 저장된 OAuth 실행 결과 확인만 사용하세요.
      </AlertMessage> : null}
      {["auth_prepared", "auth_browser_opened"].includes(enrollment.phase) && enrollment.verificationUrl && enrollment.userCode ? <div className="mt-3 rounded-md border bg-background p-3 text-sm">
        <p className="text-xs text-muted-foreground">장치 코드</p>
        <code className="mt-1 block break-all text-lg font-semibold tracking-wider">{enrollment.userCode}</code>
        <p className="mt-2 text-xs text-muted-foreground">
          「Ego Lite 인증 브라우저 열기」는 이 멤버의 전용 프로필에서 대상 계정 → 워크스페이스 → 장치코드 입력을 정확히 일치하는 항목에 한해 자동 진행합니다. 비밀번호·MFA·보안 확인 또는 모호한 화면에서는 자동화를 중단하고 같은 Space를 사용자에게 넘깁니다.
        </p>
        {enrollment.expiresInSeconds ? <p className="mt-1 text-xs text-muted-foreground">발급 시 유효시간: {enrollment.expiresInSeconds}초</p> : null}
      </div> : null}
      <dl className="mt-3 grid grid-cols-[6rem_minmax(0,1fr)] gap-2 text-xs">
        <dt>OAuth 상태</dt><dd>{enrollment.authState ?? "아직 시작하지 않음"}</dd>
        <dt>Ego 프로필</dt><dd className="break-all">{enrollment.browserProfileId ?? "아직 열지 않음"}</dd>
        <dt>Ego Task</dt><dd className="break-all">{enrollment.browserTaskSpaceId === null ? "없음" : `${enrollment.browserTaskSpaceId} · ${enrollment.browserOwnership ?? "상태 미확인"}`}</dd>
        <dt>서버 결과</dt><dd className="break-all font-mono">{enrollment.lastCode}</dd>
        <dt>마지막 기록</dt><dd className="break-all">{enrollment.updatedAt} · revision {enrollment.revision}</dd>
      </dl>
      {!error && RECOVERY_HINTS[enrollment.lastCode] ? <AlertMessage variant="warning" className="mt-3">
        {RECOVERY_HINTS[enrollment.lastCode]}
      </AlertMessage> : null}
      {enrollment.phase === "needs_attention" ? <p className="mt-3 text-xs text-destructive">
        실패를 자동 재시도하지 않습니다. 잘못된 계정으로 로그인했거나 코드가 만료된 경우 현재 결과를 확인한 뒤 작업을 명시적으로 종료하세요.
      </p> : null}
      <div className="mt-3 flex flex-wrap gap-2">
        {enrollment.phase !== "completed" && !enrollment.pendingAction && enrollment.phase !== "needs_attention" ?
          <Button size="sm" onClick={() => void runtime.resumeAuthEnrollment()} disabled={disabled || !checked}>
            남은 OAuth 절차 자동 진행
          </Button> : null}
        {enrollment.allowedActions.map((action) =>
        <Button key={action} size="sm" variant="outline" disabled={disabled || !checked}
          onClick={() => AUTH_ACTIONS[action].confirm
            ? setAuthConfirmation({ action, id: enrollment.id, revision: enrollment.revision })
            : void runtime.enrollmentCommand(action)}>{AUTH_ACTIONS[action].label}</Button>)}
      </div>
      <details className="mt-3 text-xs text-muted-foreground"><summary>OAuth 작업 식별자</summary>
        <pre className="mt-2 whitespace-pre-wrap break-all">{JSON.stringify({ enrollmentId: enrollment.id,
          handoffId: enrollment.handoffId, flowId: enrollment.flowId, pendingAction: enrollment.pendingAction }, null, 2)}</pre>
      </details>
    </div> : null}
    <AlertDialog open={confirmation !== null} onOpenChange={(open) => { if (!open) setConfirmation(null); }}>
      <AlertDialogContent className="z-[51]"><AlertDialogHeader>
        <AlertDialogTitle>{confirmation ? ACTIONS[confirmation.action].label : "단계 확인"}</AlertDialogTitle>
        <AlertDialogDescription>{confirmation ? ACTIONS[confirmation.action].confirm : ""}</AlertDialogDescription>
      </AlertDialogHeader>
        <p className="break-all text-sm">대상: {flow?.identity.targetEmail} · 제거: {flow?.removedEmail ?? "없음"}</p>
        <AlertDialogFooter><AlertDialogCancel>취소</AlertDialogCancel>
          <AlertDialogAction disabled={disabled || !checked || !confirmedFlow} onClick={() => {
            const current = confirmation; setConfirmation(null);
            if (current && confirmedFlow) void runtime.command(current.action);
          }}>이 단계 실행</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
    <AlertDialog open={authConfirmation !== null} onOpenChange={(open) => { if (!open) setAuthConfirmation(null); }}>
      <AlertDialogContent className="z-[51]"><AlertDialogHeader>
        <AlertDialogTitle>{authConfirmation ? AUTH_ACTIONS[authConfirmation.action].label : "OAuth 단계 확인"}</AlertDialogTitle>
        <AlertDialogDescription>{authConfirmation ? AUTH_ACTIONS[authConfirmation.action].confirm : ""}</AlertDialogDescription>
      </AlertDialogHeader>
        <p className="break-all text-sm">대상: {enrollment?.identity.targetEmail}</p>
        <AlertDialogFooter><AlertDialogCancel>취소</AlertDialogCancel>
          <AlertDialogAction disabled={disabled || !checked || !confirmedEnrollment} onClick={() => {
            const current = authConfirmation; setAuthConfirmation(null);
            if (current && confirmedEnrollment) void runtime.enrollmentCommand(current.action);
          }}>이 단계 실행</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </section>;
}
