from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from pydantic import ValidationError

from app.modules.member_auth_handoff.schemas import (
    MemberAuthHandoffPrepareRequest,
    MemberAuthHandoffResponse,
    WorkspaceAuthObservationResponse,
)
from app.modules.member_switch.admission import require_new_work_admission
from app.modules.member_switch.companion import CompanionPort
from app.modules.member_switch.repository import (
    GLOBAL_SCOPE,
    ControlConflict,
    ControlRecord,
    MemberSwitchControlRepository,
    command_fingerprint,
)
from app.modules.member_switch.schemas import (
    AUTH_ENROLLMENT_PROTOCOL,
    CONTROL_PROTOCOL,
    EGO_LITE_DEVICE_AUTH_AUTOMATION_CAPABILITY,
    OWNER_MEMBERSHIP_OBSERVATION_CAPABILITY,
    AuthEnrollmentAction,
    AuthEnrollmentCommandRequest,
    AuthEnrollmentCreateRequest,
    AuthEnrollmentState,
    AuthEnrollmentView,
    Catalog,
    EgoOAuthBrowserRequest,
    EgoOAuthBrowserResponse,
    EgoOAuthBrowserStatusRequest,
    EgoOAuthProfileRequest,
    Identity,
)


class AuthEnrollmentPort(Protocol):
    def bind_catalog(self, catalog: Catalog) -> None: ...
    def validate_identity(self, identity: Identity, removed_email: str | None = None) -> None: ...
    async def observe_workspace_auth(
        self, *, workspace_id: str, workspace_account_id: str
    ) -> WorkspaceAuthObservationResponse: ...
    async def prepare(
        self, request: MemberAuthHandoffPrepareRequest, *, managed_run_id: str | None = None
    ) -> MemberAuthHandoffResponse: ...
    async def advance(
        self, handoff_id: str, *, managed_run_id: str | None = None
    ) -> MemberAuthHandoffResponse | None: ...
    async def get_for_operation(self, operation_id: str) -> MemberAuthHandoffResponse | None: ...
    async def ensure_device_oauth_available(self, expected_flow_id: str | None = None) -> None: ...
    async def reconcile_for_operation(
        self, operation_id: str, *, managed_run_id: str | None = None
    ) -> MemberAuthHandoffResponse | None: ...


def enrollment_allowed_actions(state: AuthEnrollmentState, pending_action: str | None) -> list[AuthEnrollmentAction]:
    if pending_action:
        return ["reconcile"]
    if state.phase == "prepared":
        return ["prepare_auth", "cancel"]
    if state.phase == "auth_prepared":
        return ["open_auth_browser"]
    if state.phase == "auth_browser_opened":
        return ["advance_auth"]
    if state.phase in {"auth_confirmed", "needs_attention"}:
        return ["finish"]
    return []


_AUTO_OAUTH_DEADLINE_SECONDS = 180.0
_AUTO_OAUTH_POLL_SECONDS = 2.0
_AUTO_OAUTH_MAX_ADVANCE_ATTEMPTS = 30
_AUTO_BROWSER_CONTINUE_CODES = frozenset({
    "authorization_complete",
    "ego_device_auth_code_submitted",
    "ego_device_auth_code_submission_unconfirmed",
})


class MemberAuthEnrollmentService:
    """Durable OAuth-only registration for an already-current workspace member.

    This flow deliberately owns the same global control scope as member switching,
    but never calls membership mutation, recipient-session or browser participant
    APIs. The existing auth-handoff rules are reused with no removed identity, so
    no other member auth is quarantined or deleted.
    """

    def __init__(
        self,
        controls: MemberSwitchControlRepository,
        companion: CompanionPort,
        auth: AuthEnrollmentPort,
    ) -> None:
        self.controls = controls
        self.companion = companion
        self.auth = auth

    @staticmethod
    def _decode(record: ControlRecord) -> AuthEnrollmentState:
        if record.kind != "auth_enrollment":
            raise ControlConflict("auth_enrollment_record_identity_mismatch")
        try:
            state = AuthEnrollmentState.model_validate_json(record.payload)
        except ValidationError as exc:
            raise ControlConflict("stored_auth_enrollment_invalid") from exc
        if state.id != record.id:
            raise ControlConflict("auth_enrollment_record_identity_mismatch")
        return state

    @classmethod
    def _view(cls, record: ControlRecord) -> AuthEnrollmentView:
        state = cls._decode(record)
        legacy = state.control_protocol != AUTH_ENROLLMENT_PROTOCOL and state.phase != "completed"
        orphan = record.active_scope != GLOBAL_SCOPE and state.phase != "completed"
        return AuthEnrollmentView(
            id=state.id,
            revision=record.revision,
            identity=state.identity,
            phase="needs_attention"
            if legacy or orphan
            else "outcome_unknown"
            if record.pending_action
            else state.phase,
            last_code=(
                "legacy_auth_enrollment_review_required"
                if legacy
                else "orphan_auth_enrollment_retained"
                if orphan
                else state.last_code
            ),
            updated_at=state.updated_at,
            pending_action=record.pending_action,
            allowed_actions=[] if legacy or orphan else enrollment_allowed_actions(state, record.pending_action),
            handoff_id=state.handoff_id,
            auth_state=state.auth_state,
            flow_id=state.flow_id,
            verification_url=state.verification_url,
            user_code=state.user_code,
            expires_in_seconds=state.expires_in_seconds,
            browser_profile_id=state.browser_profile_id,
            browser_task_space_id=state.browser_task_space_id,
            browser_ownership=state.browser_ownership,
        )

    async def get(self, enrollment_id: str) -> AuthEnrollmentView | None:
        record = await self.controls.get(enrollment_id)
        if record is None:
            return None
        return self._view(record)

    async def active(self) -> AuthEnrollmentView | None:
        record = await self.controls.active()
        if record is None or record.kind != "auth_enrollment":
            return None
        return self._view(record)

    async def _validate_current_member(
        self,
        identity: Identity,
        *,
        allow_active_auth: bool = False,
    ) -> WorkspaceAuthObservationResponse:
        admission = await self.companion.admission()
        if not admission.can_start:
            raise ControlConflict(admission.code)
        catalog = await self.companion.catalog()
        if (
            not catalog.enabled
            or catalog.catalog_fingerprint != identity.catalog_fingerprint
            or CONTROL_PROTOCOL not in catalog.capabilities
        ):
            raise ControlConflict("catalog_identity_mismatch")
        if (
            OWNER_MEMBERSHIP_OBSERVATION_CAPABILITY not in catalog.capabilities
            or EGO_LITE_DEVICE_AUTH_AUTOMATION_CAPABILITY not in catalog.capabilities
        ):
            raise ControlConflict("companion_protocol_upgrade_required")
        workspace = next((item for item in catalog.workspaces if item.id == identity.workspace_id), None)
        target = (
            next((item for item in workspace.members if item.preset_id == identity.preset_id), None)
            if workspace
            else None
        )
        if (
            workspace is None
            or target is None
            or workspace.workspace_account_id != identity.workspace_account_id
            or target.email.casefold() != identity.target_email
            or target.user_id != identity.target_user_id
        ):
            raise ControlConflict("auth_enrollment_identity_mismatch")

        observed = await self.companion.observe_membership(workspace.id)
        if (
            observed.workspace_id != workspace.id
            or observed.workspace_account_id != workspace.workspace_account_id
            or observed.catalog_fingerprint != catalog.catalog_fingerprint
        ):
            raise ControlConflict("membership_observation_identity_mismatch")
        if (
            not observed.available
            or not observed.complete
            or not observed.owner_verified
            or observed.identity_ambiguous
            or observed.partial_identity
            or observed.duplicate_identity
            or observed.unknown_member
        ):
            raise ControlConflict(observed.code)
        if not any(
            member.classification != "owner"
            and member.email.casefold() == identity.target_email
            and member.user_id == identity.target_user_id
            for member in observed.members
        ):
            raise ControlConflict("oauth_enrollment_member_not_current")

        self.auth.bind_catalog(catalog)
        self.auth.validate_identity(identity)
        auth_observation = await self.auth.observe_workspace_auth(
            workspace_id=workspace.id,
            workspace_account_id=workspace.workspace_account_id,
        )
        if not auth_observation.available or auth_observation.catalog_fingerprint != catalog.catalog_fingerprint:
            raise ControlConflict(auth_observation.code)
        if auth_observation.identity_ambiguous:
            raise ControlConflict("member_auth_identity_ambiguous")
        auth_member = next(
            (
                member
                for member in auth_observation.members
                if member.preset_id == identity.preset_id
                and member.email.casefold() == identity.target_email
                and member.user_id == identity.target_user_id
            ),
            None,
        )
        if auth_member is None:
            raise ControlConflict("member_auth_observation_mismatch")
        if auth_member.state == "active" and not allow_active_auth:
            raise ControlConflict("member_auth_already_active")
        if auth_member.state == "handoff_quarantined":
            raise ControlConflict("member_auth_quarantined")
        if auth_member.state == "ambiguous":
            raise ControlConflict("member_auth_identity_ambiguous")
        return auth_observation

    async def create(self, request: AuthEnrollmentCreateRequest) -> AuthEnrollmentView:
        enrollment_id = str(request.enrollment_id)
        fingerprint = command_fingerprint("create_auth_enrollment", request.model_dump_json())
        existing = await self.controls.get(enrollment_id)
        if existing is not None:
            state = self._decode(existing)
            if state.create_request_hash != fingerprint:
                raise ControlConflict("auth_enrollment_identity_mismatch")
            return self._view(existing)

        await require_new_work_admission(self.controls)
        catalog = await self.companion.catalog()
        workspace = next((item for item in catalog.workspaces if item.id == request.workspace_id), None)
        target = (
            next((item for item in workspace.members if item.preset_id == request.preset_id), None)
            if workspace
            else None
        )
        if (
            workspace is None
            or target is None
            or catalog.catalog_fingerprint != request.catalog_fingerprint
            or target.email.casefold() != request.member_email.casefold()
            or target.user_id != request.member_user_id
        ):
            raise ControlConflict("auth_enrollment_identity_mismatch")
        identity = Identity(
            workspace_id=workspace.id,
            workspace_account_id=workspace.workspace_account_id,
            preset_id=target.preset_id,
            target_email=target.email.casefold(),
            target_user_id=target.user_id,
            catalog_fingerprint=catalog.catalog_fingerprint,
        )
        await self._validate_current_member(identity)
        state = AuthEnrollmentState(
            control_protocol=AUTH_ENROLLMENT_PROTOCOL,
            id=enrollment_id,
            create_request_hash=fingerprint,
            identity=identity,
            operation_id="oauth-enrollment:" + enrollment_id,
            phase="prepared",
            last_code="oauth_enrollment_ready",
            updated_at=datetime.now(timezone.utc),
        )
        record = await self.controls.create(enrollment_id, "auth_enrollment", state.model_dump_json(), own_scope=True)
        return self._view(record)

    async def create_and_auto_complete(self, request: AuthEnrollmentCreateRequest) -> AuthEnrollmentView:
        """Create or resume one current-member OAuth enrollment through safe terminal completion.

        Each external stage remains an ordinary durable command. Retries derive the next action
        from stored state, reconcile any retained command before continuing, and never replay a
        completed browser/device-code effect. Only OAuth observation/application is polled.
        """
        view = await self.create(request)
        return await self.auto_complete(view.id)

    async def auto_complete(self, enrollment_id: str, *, allow_manual_resume: bool = False) -> AuthEnrollmentView:
        deadline = time.monotonic() + _AUTO_OAUTH_DEADLINE_SECONDS
        advance_attempts = 0
        while True:
            record = await self.controls.get(enrollment_id)
            if record is None:
                raise ControlConflict("auth_enrollment_not_found")
            state = self._decode(record)
            view = self._view(record)
            if state.phase == "completed":
                return view
            if state.phase == "needs_attention":
                return view

            if record.pending_action:
                try:
                    view = await self.command(
                        enrollment_id,
                        AuthEnrollmentCommandRequest(
                            command_id=uuid4(), expected_revision=record.revision, action="reconcile"
                        ),
                    )
                except ControlConflict:
                    # A retained unknown effect is not permission to replay it. Leave the exact
                    # durable record visible for explicit recovery when observation cannot settle it.
                    return self._view((await self.controls.get(enrollment_id)) or record)
                if view.phase == "completed":
                    return view
                continue

            if state.phase == "prepared":
                action: AuthEnrollmentAction = "prepare_auth"
            elif state.phase == "auth_prepared":
                action = "open_auth_browser"
            elif state.phase == "auth_browser_opened":
                # Manual challenges/ambiguous pages are intentionally handed to the operator.
                # Only a browser result proving code submission/completion authorizes automatic
                # OAuth observation/application.
                can_observe_after_manual = (
                    allow_manual_resume and state.last_code == "ego_device_auth_user_action_required"
                )
                if (
                    state.last_code not in _AUTO_BROWSER_CONTINUE_CODES
                    and state.auth_state not in {"oauth_pending", "oauth_verified"}
                    and not can_observe_after_manual
                ):
                    return view
                if time.monotonic() >= deadline or advance_attempts >= _AUTO_OAUTH_MAX_ADVANCE_ATTEMPTS:
                    return view
                action = "advance_auth"
            elif state.phase == "auth_confirmed":
                if state.auth_state != "completed":
                    return view
                action = "finish"
            else:
                return view

            try:
                next_view = await self.command(
                    enrollment_id,
                    AuthEnrollmentCommandRequest(
                        command_id=uuid4(), expected_revision=view.revision, action=action
                    ),
                )
            except ControlConflict:
                current = await self.controls.get(enrollment_id)
                if current is not None and current.pending_action:
                    # The next loop iteration performs observation-only reconciliation.
                    continue
                raise

            if action == "open_auth_browser" and (
                next_view.phase != "auth_browser_opened"
                or next_view.last_code not in _AUTO_BROWSER_CONTINUE_CODES
            ):
                return next_view
            if action == "advance_auth" and next_view.phase == "auth_browser_opened":
                advance_attempts += 1
                if time.monotonic() >= deadline or advance_attempts >= _AUTO_OAUTH_MAX_ADVANCE_ATTEMPTS:
                    return next_view
                await asyncio.sleep(_AUTO_OAUTH_POLL_SECONDS)
            view = next_view

    async def _save(
        self, record: ControlRecord, state: AuthEnrollmentState, *, release: bool = False
    ) -> AuthEnrollmentView:
        state = state.model_copy(update={"updated_at": datetime.now(timezone.utc)})
        saved = await self.controls.save(
            record,
            state.model_dump_json(),
            complete=True,
            release=release,
        )
        return self._view(saved)

    @staticmethod
    def _accept_auth(state: AuthEnrollmentState, auth: MemberAuthHandoffResponse) -> AuthEnrollmentState:
        identity = state.identity
        if (
            auth.member_switch_operation_id != state.operation_id
            or auth.workspace_account_id != identity.workspace_account_id
            or auth.preset_id != identity.preset_id
            or auth.target_email.casefold() != identity.target_email
            or auth.target_user_id != identity.target_user_id
            or auth.removed_email is not None
            or (state.handoff_id is not None and auth.handoff_id != state.handoff_id)
        ):
            raise ControlConflict("auth_enrollment_handoff_identity_mismatch")
        if auth.pending_action:
            raise ControlConflict("handoff_outcome_unknown")
        phase = (
            "auth_confirmed"
            if auth.state == "completed"
            else "needs_attention"
            if auth.state == "failed"
            else "auth_browser_opened"
            if state.browser_task_space_id is not None
            else "auth_prepared"
        )
        return state.model_copy(
            update={
                "handoff_id": auth.handoff_id,
                "auth_state": auth.state,
                "phase": phase,
                "last_code": auth.error_code or auth.state,
                "flow_id": auth.flow_id,
                "verification_url": auth.verification_url,
                "user_code": auth.user_code,
                "expires_in_seconds": auth.expires_in_seconds,
            }
        )

    @staticmethod
    def _browser_request(state: AuthEnrollmentState) -> EgoOAuthBrowserRequest:
        if state.verification_url is None:
            raise ControlConflict("verification_url_missing")
        if state.user_code is None:
            raise ControlConflict("user_code_missing")
        identity = state.identity
        return EgoOAuthBrowserRequest(
            enrollment_id=state.id,
            workspace_id=identity.workspace_id,
            workspace_account_id=identity.workspace_account_id,
            preset_id=identity.preset_id,
            target_email=identity.target_email,
            target_user_id=identity.target_user_id,
            catalog_fingerprint=identity.catalog_fingerprint,
            verification_url=state.verification_url,
            user_code=state.user_code,
        )

    @staticmethod
    def _profile_request(state: AuthEnrollmentState) -> EgoOAuthProfileRequest:
        identity = state.identity
        return EgoOAuthProfileRequest(
            workspace_id=identity.workspace_id,
            workspace_account_id=identity.workspace_account_id,
            preset_id=identity.preset_id,
            target_email=identity.target_email,
            target_user_id=identity.target_user_id,
            catalog_fingerprint=identity.catalog_fingerprint,
        )

    @classmethod
    def _browser_status_request(cls, state: AuthEnrollmentState) -> EgoOAuthBrowserStatusRequest:
        request = cls._browser_request(state)
        return EgoOAuthBrowserStatusRequest.model_validate(request.model_dump(exclude={"user_code"}))

    @staticmethod
    def _accept_browser(
        state: AuthEnrollmentState,
        browser: EgoOAuthBrowserResponse,
    ) -> AuthEnrollmentState:
        if browser.enrollment_id != state.id:
            raise ControlConflict("ego_browser_enrollment_identity_mismatch")
        if browser.outcome_unknown:
            return state.model_copy(
                update={
                    "last_code": browser.code,
                    "browser_profile_id": browser.profile_id or state.browser_profile_id,
                    "browser_task_space_id": browser.task_space_id or state.browser_task_space_id,
                    "browser_ownership": browser.ownership or state.browser_ownership,
                }
            )
        if not browser.accepted:
            return state.model_copy(update={"last_code": browser.code})
        if (
            not browser.profile_id
            or browser.task_space_id is None
            or browser.ownership != "agentDelegatedToUser"
        ):
            raise ControlConflict("ego_browser_response_invalid")
        return state.model_copy(
            update={
                "phase": "auth_browser_opened",
                "last_code": browser.code,
                "browser_profile_id": browser.profile_id,
                "browser_task_space_id": browser.task_space_id,
                "browser_ownership": browser.ownership,
            }
        )

    async def command(self, enrollment_id: str, request: AuthEnrollmentCommandRequest) -> AuthEnrollmentView:
        record = await self.controls.get(enrollment_id)
        if record is None:
            raise ControlConflict("auth_enrollment_not_found")
        state = self._decode(record)
        if state.control_protocol != AUTH_ENROLLMENT_PROTOCOL:
            raise ControlConflict("legacy_auth_enrollment_review_required")
        if record.active_scope != GLOBAL_SCOPE and state.phase != "completed":
            raise ControlConflict("orphan_auth_enrollment_retained")
        fingerprint = command_fingerprint(request.action, request.model_dump_json())
        if await self.controls.command_recorded(record.id, str(request.command_id), fingerprint):
            return self._view(record)
        if request.expected_revision != record.revision:
            raise ControlConflict("revision_conflict")
        if request.action not in enrollment_allowed_actions(state, record.pending_action):
            raise ControlConflict("transition_not_allowed")
        if request.action == "reconcile":
            return await self._reconcile(record, state)

        if request.action == "prepare_auth":
            await require_new_work_admission(self.controls, owning_run_id=enrollment_id)
            await self._validate_current_member(state.identity)
            profile = await self.companion.ego_oauth_profile_status(self._profile_request(state))
            if not profile.ready:
                raise ControlConflict(profile.code)
            await self.auth.ensure_device_oauth_available()

        if request.action == "advance_auth":
            await require_new_work_admission(self.controls, owning_run_id=enrollment_id)
            await self._validate_current_member(state.identity, allow_active_auth=True)
            await self.auth.ensure_device_oauth_available(state.flow_id)

        if request.action == "open_auth_browser":
            await require_new_work_admission(self.controls, owning_run_id=enrollment_id)
            await self._validate_current_member(state.identity)
            if (
                state.handoff_id is None
                or state.flow_id is None
                or state.verification_url is None
                or state.user_code is None
            ):
                raise ControlConflict("auth_enrollment_browser_not_ready")

        record, execute = await self.controls.claim(
            record,
            str(request.command_id),
            request.action,
            fingerprint,
            expected_revision=request.expected_revision,
        )
        if not execute:
            return self._view(record)

        if request.action == "prepare_auth":
            auth = await self.auth.prepare(
                MemberAuthHandoffPrepareRequest(
                    member_switch_operation_id=state.operation_id,
                    preset_id=state.identity.preset_id,
                    workspace_account_id=state.identity.workspace_account_id,
                    removed_email=None,
                    removed_user_id=None,
                    target_email=state.identity.target_email,
                    target_user_id=state.identity.target_user_id,
                    membership_state="active",
                    catalog_fingerprint=state.identity.catalog_fingerprint,
                    preserve_other_auth=True,
                ),
                managed_run_id=state.id,
            )
            state = self._accept_auth(state, auth)
        elif request.action == "open_auth_browser":
            browser = await self.companion.open_ego_oauth_browser(self._browser_request(state))
            state = self._accept_browser(state, browser)
            if browser.outcome_unknown:
                await self.controls.save(record, state.model_dump_json())
                raise ControlConflict(browser.code)
        elif request.action == "advance_auth":
            if state.handoff_id is None:
                raise ControlConflict("handoff_missing")
            auth = await self.auth.advance(state.handoff_id, managed_run_id=state.id)
            if auth is None:
                raise ControlConflict("handoff_missing")
            state = self._accept_auth(state, auth)
        elif request.action == "finish":
            if state.auth_state not in {"completed", "failed"}:
                raise ControlConflict("auth_enrollment_not_terminal")
            state = state.model_copy(update={"phase": "completed", "last_code": "auth_enrollment_finalized"})
        elif request.action == "cancel":
            state = state.model_copy(update={"phase": "completed", "last_code": "auth_enrollment_cancelled"})
        return await self._save(record, state, release=state.phase == "completed")

    async def _reconcile(self, record: ControlRecord, state: AuthEnrollmentState) -> AuthEnrollmentView:
        action = record.pending_action
        if action in {"prepare_auth", "advance_auth"}:
            auth = await self.auth.reconcile_for_operation(
                state.operation_id,
                managed_run_id=state.id,
            )
            if auth is None:
                raise ControlConflict("auth_outcome_still_unknown")
            if auth.last_command_id != record.command_id:
                raise ControlConflict("auth_receipt_not_current")
            state = self._accept_auth(state, auth)
        elif action == "open_auth_browser":
            browser = await self.companion.ego_oauth_browser_status(self._browser_status_request(state))
            state = self._accept_browser(state, browser)
            if browser.outcome_unknown or not browser.accepted:
                raise ControlConflict(browser.code)
        elif action == "finish":
            if state.auth_state not in {"completed", "failed"}:
                raise ControlConflict("auth_enrollment_not_terminal")
            state = state.model_copy(update={"phase": "completed", "last_code": "auth_enrollment_finalized"})
        elif action == "cancel":
            state = state.model_copy(update={"phase": "completed", "last_code": "auth_enrollment_cancelled"})
        else:
            raise ControlConflict("external_receipt_unavailable_manual_review_required")
        return await self._save(record, state, release=state.phase == "completed")
