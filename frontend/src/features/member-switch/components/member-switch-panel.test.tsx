import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api-client";
import * as client from "@/features/member-switch/run-client";
import { MemberSwitchPanel } from "./member-switch-panel";
import {
  installMemberSwitchMocks,
  makeAuthEnrollmentView,
  makeRunView,
  memberIdentity,
} from "@/test/mocks/member-switch";
describe("manual server-owned panel", () => {
  let mock: ReturnType<typeof installMemberSwitchMocks>;
  beforeEach(() => { localStorage.clear(); sessionStorage.clear(); mock = installMemberSwitchMocks(); });
  it.each([true, false])("owner preflight recovery uses only available controls (finish=%s)", async (canFinish) => {
    mock.run = makeRunView({phase: "needs_attention", lastCode: "ego_owner_profile_login_required",
      operationId: "operation-1", allowedActions: canFinish ? ["observe_membership", "finish"] : ["observe_membership"]});
    render(<MemberSwitchPanel readOnly={false} />);
    await screen.findByRole("button", {name: "멤버 상태 확인"});
    const flow = screen.getByRole("heading", {name: "별도 확인 필요"}).parentElement!;
    expect(within(flow).queryByText(/로그인한 뒤 목록 새로고침을 다시 실행하세요/)).not.toBeInTheDocument();
    if (canFinish) {
      expect(within(flow).getByRole("button", {name: "종료 확인"})).toBeEnabled();
      expect(within(flow).getByText(/「종료 확인」으로 현재 작업을 종료한 뒤/)).toBeInTheDocument();
    } else {
      expect(within(flow).queryByRole("button", {name: "종료 확인"})).not.toBeInTheDocument();
      expect(within(flow).getByText(/종료가 허용되지 않은 상태/)).toBeInTheDocument();
    }
    expect(mock.requests.filter(item => item.method === "POST")).toEqual([]);
  });
  it("pending owner closeout guidance names reconciliation rather than unavailable membership action", async () => {
    mock.run = makeRunView({phase:"outcome_unknown",pendingAction:"finish",lastCode:"ego_owner_profile_login_required",
      operationId:"operation-1",allowedActions:["reconcile"]});
    render(<MemberSwitchPanel readOnly={false} />);
    const button=await screen.findByRole("button",{name:"저장된 실행 결과 확인"});
    await waitFor(() => expect(button).toBeEnabled());
    const flow=screen.getByRole("heading",{name:"실행 결과 미확정"}).parentElement!;
    expect(within(flow).queryByRole("button",{name:"멤버 상태 확인"})).not.toBeInTheDocument();
    expect(within(flow).queryByText(/「멤버 상태 확인」/)).not.toBeInTheDocument();
    expect(within(flow).getByText(/「저장된 실행 결과 확인」으로 현재 요청의 결과/)).toBeInTheDocument();
    expect(mock.requests.filter(item => item.method==="POST")).toEqual([]);
  });

  it("pending membership observation is not described as a termination request", async () => {
    mock.run=makeRunView({phase:"outcome_unknown",pendingAction:"observe_membership",
      lastCode:"ego_owner_profile_login_required",operationId:"operation-1",allowedActions:["reconcile"]});
    render(<MemberSwitchPanel readOnly={false} />);
    await screen.findByRole("button",{name:"저장된 실행 결과 확인"});
    const flow=screen.getByRole("heading",{name:"실행 결과 미확정"}).parentElement!;
    expect(within(flow).queryByText(/종료 요청의 완료 여부/)).not.toBeInTheDocument();
    expect(within(flow).getByText(/「저장된 실행 결과 확인」으로 현재 요청의 결과/)).toBeInTheDocument();
  });

  it("requires an explicit confirmation for membership mutation and Cancel does not submit", async () => {
    const user = userEvent.setup(); render(<MemberSwitchPanel readOnly={false} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "목록 불러오기" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "목록 불러오기" }));
    const target = await screen.findByRole("button", { name: /Target member/ });
    await waitFor(() => expect(target).toBeEnabled()); await user.click(target);
    await user.click(await screen.findByRole("button", { name: "교체 요청 1회" }));
    const cancel = await screen.findByRole("button", { name: "취소" }); cancel.focus(); await user.keyboard("{Enter}");
    expect(mock.requests.filter((item) => item.path.endsWith("/commands"))).toEqual([]);
  });
  it("loads actual workspace membership through the owner Ego Lite path", async () => {
    const user = userEvent.setup(); render(<MemberSwitchPanel readOnly={false} />);
    expect(screen.getByText(/각 워크스페이스 소유주 ID의 Ego Lite 프로필\/Space/)).toBeInTheDocument();
    expect(screen.getByText(/소유주 멤버 삭제·초대·초대취소와 그 전후 개인 계정 확인도 동일한 소유주 Ego Lite Space/)).toBeInTheDocument();
    expect(screen.getByText(/기존 owner CDP를 대체 경로로 사용하지 않습니다/)).toBeInTheDocument();
    expect(screen.getByText(/수신자의 Personal 확인, 워크스페이스 존재·부재 확인, 초대 수락도 해당 ID의 Ego Lite/)).toBeInTheDocument();
    expect(screen.getByText(/managed 멤버 전환 중에는 recipient CDP로 fallback하지 않습니다/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "목록 불러오기" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "목록 불러오기" }));
    expect(await screen.findByText("소유주: owner@example.com")).toBeInTheDocument();
    expect(screen.getByText("멤버: current@example.com")).toBeInTheDocument();
    expect(screen.getByText("전환 후보")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Target member/ })).toBeInTheDocument();
    expect(mock.requests.filter((item) => item.path.endsWith("/catalog/refresh"))).toHaveLength(1);
  });
  it("completes current-member OAuth registration from one click on the normal path", async () => {
    mock.catalog.workspaces[0].currentMembers = [{
      email: memberIdentity.targetEmail,
      userId: memberIdentity.targetUserId,
      presetId: memberIdentity.presetId,
      authState: "absent",
      authAccountId: null,
    }];
    const user = userEvent.setup(); render(<MemberSwitchPanel readOnly={false} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "목록 불러오기" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "목록 불러오기" }));
    expect(await screen.findByText("OAuth 미등록")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "OAuth 등록" }));

    expect(await screen.findByText("OAuth 등록됨")).toBeInTheDocument();
    expect(await screen.findByText(/강제 Probe 완료 · 연결 정상 · 토큰 사용 가능 · HTTP 200/)).toBeInTheDocument();
    expect(screen.queryByText(/현재 멤버 OAuth 등록 ·/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "장치 코드 발급" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ego Lite 인증 브라우저 열기" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "인증 확인·반영" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "완료 기록 닫기" })).not.toBeInTheDocument();
    expect(mock.requests.filter((item) => item.path === "/api/member-switch-runs/oauth-enrollments/auto")).toHaveLength(1);
    expect(mock.requests.filter((item) => item.path.endsWith("/commands"))).toHaveLength(0);
    expect(mock.requests.filter((item) => item.path === "/api/accounts/auth-target/probe")).toHaveLength(0);
  });
  it("shows quota exhaustion returned by the server-owned post-registration Probe", async () => {
    mock.probeStatusCode = 429;
    mock.probePrimaryUsedPercentAfter = 100;
    mock.catalog.workspaces[0].currentMembers = [{
      email: memberIdentity.targetEmail,
      userId: memberIdentity.targetUserId,
      presetId: memberIdentity.presetId,
      authState: "absent",
      authAccountId: null,
    }];
    const user = userEvent.setup(); render(<MemberSwitchPanel readOnly={false} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "목록 불러오기" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "목록 불러오기" }));
    await user.click(await screen.findByRole("button", { name: "OAuth 등록" }));

    expect(await screen.findByText(/강제 Probe 완료 · quota 제한 확인 · HTTP 429/)).toBeInTheDocument();
    expect(screen.getByText(/1차 사용량 100%/)).toBeInTheDocument();
    expect(mock.requests.filter((item) => item.path === "/api/accounts/auth-target/probe")).toHaveLength(0);
  });

  it("prioritizes refreshed 100% quota over a 2xx Probe status", async () => {
    mock.probeStatusCode = 200;
    mock.probePrimaryUsedPercentAfter = 100;
    mock.catalog.workspaces[0].currentMembers = [{
      email: memberIdentity.targetEmail, userId: memberIdentity.targetUserId, presetId: memberIdentity.presetId,
      authState: "absent", authAccountId: null,
    }];
    const user = userEvent.setup(); render(<MemberSwitchPanel readOnly={false} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "목록 불러오기" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "목록 불러오기" }));
    await user.click(await screen.findByRole("button", { name: "OAuth 등록" }));

    expect(await screen.findByText(/강제 Probe 완료 · quota 제한 확인 · HTTP 200/)).toBeInTheDocument();
    expect(screen.getByText(/1차 사용량 100%/)).toBeInTheDocument();
  });

  it("does not call a rejected Probe request a connection failure when token usage refresh succeeded", async () => {
    mock.probeStatusCode = 400;
    mock.probePrimaryUsedPercentAfter = 0;
    mock.probeUsageRefreshSucceeded = true;
    mock.catalog.workspaces[0].currentMembers = [{
      email: memberIdentity.targetEmail,
      userId: memberIdentity.targetUserId,
      presetId: memberIdentity.presetId,
      authState: "absent",
      authAccountId: null,
    }];
    const user = userEvent.setup(); render(<MemberSwitchPanel readOnly={false} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "목록 불러오기" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "목록 불러오기" }));
    await user.click(await screen.findByRole("button", { name: "OAuth 등록" }));

    expect(await screen.findByText(/강제 Probe 요청 HTTP 400 · OAuth 토큰·Usage 조회 정상/)).toBeInTheDocument();
    expect(screen.getByText(/1차 사용량 0%/)).toBeInTheDocument();
    expect(screen.queryByText(/강제 Probe 연결 확인 실패/)).not.toBeInTheDocument();
    expect(mock.requests.filter((item) => item.path === "/api/accounts/auth-target/probe")).toHaveLength(0);
  });

  it("shows persisted OAuth phase progress while the one-click request is still running", async () => {
    mock.autoEnrollmentDelayMs = 700;
    mock.catalog.workspaces[0].currentMembers = [{
      email: memberIdentity.targetEmail,
      userId: memberIdentity.targetUserId,
      presetId: memberIdentity.presetId,
      authState: "absent",
      authAccountId: null,
    }];
    const user = userEvent.setup(); render(<MemberSwitchPanel readOnly={false} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "목록 불러오기" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "목록 불러오기" }));
    await user.click(await screen.findByRole("button", { name: "OAuth 등록" }));

    expect(await screen.findByText("장치 코드 발급 완료 · Ego Lite 인증 시작 중", {}, { timeout: 2_000 })).toBeInTheDocument();
    expect(mock.requests.filter((item) => item.method === "GET" && /\/oauth-enrollments\/[^/]+$/.test(item.path)).length).toBeGreaterThan(0);
    expect(mock.requests.filter((item) => item.path.endsWith("/commands"))).toHaveLength(0);
    expect(await screen.findByText(/강제 Probe 완료 · 연결 정상 · 토큰 사용 가능 · HTTP 200/, {}, { timeout: 2_000 })).toBeInTheDocument();
  });

  it("reports Force Probe token failure separately after OAuth registration succeeds", async () => {
    mock.probeErrorCode = "account_probe_refresh_failed";
    mock.catalog.workspaces[0].currentMembers = [{
      email: memberIdentity.targetEmail,
      userId: memberIdentity.targetUserId,
      presetId: memberIdentity.presetId,
      authState: "absent",
      authAccountId: null,
    }];
    const user = userEvent.setup(); render(<MemberSwitchPanel readOnly={false} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "목록 불러오기" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "목록 불러오기" }));
    await user.click(await screen.findByRole("button", { name: "OAuth 등록" }));

    expect(await screen.findByText("OAuth 등록됨")).toBeInTheDocument();
    expect(await screen.findByText("OAuth 등록은 완료됐습니다. 강제 Probe에서 토큰 갱신에 실패했습니다.")).toBeInTheDocument();
    expect(screen.queryByText(/OAuth 등록 실패/)).not.toBeInTheDocument();
  });

  it("shows only recovery controls when one-click OAuth stops for manual authentication", async () => {
    mock.autoEnrollmentResult = "manual";
    mock.catalog.workspaces[0].currentMembers = [{
      email: memberIdentity.targetEmail,
      userId: memberIdentity.targetUserId,
      presetId: memberIdentity.presetId,
      authState: "absent",
      authAccountId: null,
    }];
    const user = userEvent.setup(); render(<MemberSwitchPanel readOnly={false} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "목록 불러오기" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "목록 불러오기" }));
    await user.click(await screen.findByRole("button", { name: "OAuth 등록" }));

    expect(await screen.findByText(/현재 멤버 OAuth 등록 · Ego Lite 인증 브라우저 열림/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "남은 OAuth 절차 자동 진행" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "인증 확인·반영" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "장치 코드 발급" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ego Lite 인증 브라우저 열기" })).not.toBeInTheDocument();
  });
  it("does not offer OAuth registration when the current member auth is already active", async () => {
    mock.catalog.workspaces[0].currentMembers = [{
      email: memberIdentity.targetEmail,
      userId: memberIdentity.targetUserId,
      presetId: memberIdentity.presetId,
      authState: "active",
      authAccountId: "auth-target",
    }];
    const user = userEvent.setup(); render(<MemberSwitchPanel readOnly={false} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "목록 불러오기" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "목록 불러오기" }));
    expect(await screen.findByText("OAuth 등록됨")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /OAuth .*등록/ })).not.toBeInTheDocument();
  });
  it("separates membership completion, auth observation and explicit auth mutation", async () => {
    mock.run = makeRunView({ phase: "membership_confirmed", operationId: "operation-1", allowedActions: ["observe_membership", "prepare_session"] });
    const user = userEvent.setup(); render(<MemberSwitchPanel readOnly={false} />);
    expect(await screen.findByText(/멤버 등록 완료는 auth 전환 완료가 아닙니다/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "종료 확인" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "인증 준비" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Ego Lite 로그인 확인" }));
    await user.click(screen.getByRole("button", { name: "이 단계 실행" }));
    await user.click(await screen.findByRole("button", { name: "인증 준비" }));
    expect(await screen.findByRole("alertdialog")).toHaveTextContent(/아직 기존 auth를 삭제하지 않습니다/);
    await user.click(screen.getByRole("button", { name: "이 단계 실행" }));
    await user.click(await screen.findByRole("button", { name: "인증 진행·반영" }));
    expect(await screen.findByRole("alertdialog")).toHaveTextContent(/단순 조회가 아닙니다/);
    expect(screen.getByRole("button", { name: "인증 상태 읽기" })).toBeInTheDocument();
  });
  it("does not offer reset, finish or replay when the server reports an unknown outcome", async () => {
    mock.run = makeRunView({ phase: "outcome_unknown", pendingAction: "start", allowedActions: ["reconcile"] });
    render(<MemberSwitchPanel readOnly={false} />);
    expect(await screen.findByRole("button", { name: "저장된 실행 결과 확인" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "교체 요청 1회" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "종료 확인" })).not.toBeInTheDocument();
  });
  it("explains when a retained failed run is safe to close without membership replay", async () => {
    mock.run = makeRunView({
      phase: "needs_attention",
      lastCode: "personal_switch_not_confirmed",
      operationId: "operation-1",
      allowedActions: ["observe_membership", "finish"],
    });
    render(<MemberSwitchPanel readOnly={false} />);
    expect(await screen.findByText(/멤버 변경 동작이 시작되기 전에 확정 실패한 작업/)).toBeInTheDocument();
    expect(screen.getByText(/보존된 작업 소유권만 정상 종료/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "종료 확인" })).toBeEnabled();
  });
  it("offers executable same-handoff login recovery after closing an unfinished auth page", async () => {
    mock.run = makeRunView({ phase: "auth_prepared", operationId: "operation-1",
      handoffId: "handoff-1", authState: "device_code_issued", browserOperationId: null,
      lastCode: "ego_member_session_not_prepared", allowedActions: ["observe_auth", "advance_auth", "prepare_session", "open_browser"] });
    const user = userEvent.setup(); render(<MemberSwitchPanel readOnly={false} />);
    expect(await screen.findByText(/기존 인증 작업과 장치 코드는 유지됩니다/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Ego Lite 로그인 확인" }));
    expect(await screen.findByRole("alertdialog")).toHaveTextContent(/이미 발급된 인증 작업과 장치 코드는 유지/);
    await user.click(screen.getByRole("button", { name: "이 단계 실행" }));
    expect(await screen.findByRole("button", { name: "ID 전용 Ego Lite 열기" })).toBeEnabled();
    expect(mock.run?.handoffId).toBe("handoff-1");
    expect(screen.queryByRole("button", { name: "인증 준비" })).not.toBeInTheDocument();
    const requests = mock.requests.filter(r => r.method === "POST" && r.path.endsWith("/commands"));
    expect(requests).toHaveLength(1);
  });
  it("does not describe a transient identity query failure as a logout", async () => {
    mock.run = makeRunView({ phase: "membership_confirmed", lastCode: "ego_browser_identity_unavailable",
      operationId: "operation-1", allowedActions: ["prepare_session"] });
    render(<MemberSwitchPanel readOnly={false} />);
    expect(await screen.findByText(/로그아웃되었다는 뜻은 아닙니다/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ego Lite 로그인 확인" })).toBeEnabled();
  });
  it("read-only access cannot fetch or execute control actions", () => {
    render(<MemberSwitchPanel readOnly />);
    expect(screen.getByRole("button", { name: "목록 불러오기" })).toBeDisabled();
    expect(mock.requests).toEqual([]);
  });
  it("explains that an expired OAuth-only device code must start a new enrollment", async () => {
    mock.enrollment = makeAuthEnrollmentView({
      phase: "needs_attention",
      lastCode: "device_code_expired_requires_new_enrollment",
      authState: "failed",
      verificationUrl: "https://auth.example/expired-device",
      userCode: "OLD-CODE",
      allowedActions: ["finish"],
    });
    render(<MemberSwitchPanel readOnly={false} />);
    expect(await screen.findByText(/장치 코드가 만료되었습니다/)).toBeInTheDocument();
    expect(screen.getByText(/자동 재발급하지 않습니다/)).toBeInTheDocument();
    expect(screen.queryByText("OLD-CODE", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "인증 페이지 열기" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "OAuth 작업 종료 확인" })).toBeEnabled();
  });
  it("explains a changed device code and confirms close without finishing the run", async () => {
    mock.run = makeRunView({ phase: "auth_browser_opened", operationId: "operation-1",
      handoffId: "handoff-1", authState: "device_code_issued", browserOperationId: "browser-1",
      lastCode: "auth_browser_code_changed", allowedActions: ["observe_auth", "advance_auth", "close_browser"] });
    const user = userEvent.setup(); render(<MemberSwitchPanel readOnly={false} />);
    expect(await screen.findByText(/인증 코드가 재발급되었습니다/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Ego Lite 종료" }));
    expect(await screen.findByRole("alertdialog")).toHaveTextContent(/이 작업에 속한 ID 전용 Ego Lite Task Space/);
    expect(mock.requests.filter((item) => item.method === "POST")).toEqual([]);
    await user.click(screen.getByRole("button", { name: "이 단계 실행" }));
    expect(await screen.findByRole("button", { name: "Ego Lite 로그인 확인" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "ID 전용 Ego Lite 열기" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "종료 확인" })).not.toBeInTheDocument();
    expect(mock.run?.phase).toBe("needs_attention");
    await user.click(screen.getByRole("button", { name: "Ego Lite 로그인 확인" }));
    await user.click(await screen.findByRole("button", { name: "이 단계 실행" }));
    expect(await screen.findByRole("button", { name: "ID 전용 Ego Lite 열기" })).toBeEnabled();
  });
  it("explains owner-login failures and blocks only that workspace's candidates", async () => {
    const broken = mock.catalog.workspaces[0];
    mock.catalog.workspaces.push({ ...broken, id:"cdp-2", workspaceName:"Healthy workspace",
      workspaceAccountId:"11111111-1111-4111-8111-111111111111",
      members:[{...broken.members[0],presetId:"healthy-target",displayName:"Healthy target"}] });
    broken.membershipCode = "ego_owner_profile_login_required";
    broken.currentMembers = [];
    broken.membershipObservedAt = null;
    const user = userEvent.setup(); render(<MemberSwitchPanel readOnly={false}/>);
    await waitFor(() => expect(screen.getByRole("button", {name:"목록 불러오기"})).toBeEnabled());
    await user.click(screen.getByRole("button", {name:"목록 불러오기"}));
    const section = (await screen.findByRole("heading", {name:"Test workspace"})).closest("section")!;
    expect(within(section).getByRole("button", {name:/Target member/})).toBeDisabled();
    expect(within(section).getByText(/열린 소유주 Space/)).toBeInTheDocument();
    expect(within(section).getByText(/ego_owner_profile_login_required/)).toBeInTheDocument();
    expect(screen.getByRole("button", {name:/Healthy target/})).toBeEnabled();
    expect(mock.requests.filter(item => item.path === "/api/member-switch-runs")).toHaveLength(0);
  });

  it("keeps live catalog disabled until the stored-state error is resolved", async () => {
    const get = vi.spyOn(client, "getActiveRun").mockRejectedValueOnce(
      new ApiError({status:503,code:"request_failed",message:"Unavailable"}));
    try {
      const user = userEvent.setup(); render(<MemberSwitchPanel readOnly={false}/>);
      expect(await screen.findByRole("alert")).toHaveTextContent("request_failed");
      expect(screen.getByRole("button", {name:"목록 불러오기"})).toBeDisabled();
      expect(screen.getByRole("button", {name:"서버 기록 새로고침"})).toBeEnabled();
      get.mockResolvedValue({run:null});
      await user.click(screen.getByRole("button", {name:"서버 기록 새로고침"}));
      await waitFor(() => expect(screen.getByRole("button", {name:"목록 불러오기"})).toBeEnabled());
    } finally {get.mockRestore();}
  });

});
