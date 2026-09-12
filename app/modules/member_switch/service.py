from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from pydantic import ValidationError

from app.modules.member_auth_handoff.schemas import (
    MemberAuthHandoffPrepareRequest,
    MemberAuthHandoffResponse,
    WorkspaceAuthObservationResponse,
)
from app.modules.member_switch.admission import require_new_work_admission
from app.modules.member_switch.companion import CompanionPort
from app.modules.member_switch.participants import accept_participant, participant_fingerprint
from app.modules.member_switch.policy import allowed_actions, membership_confirmed, require_operation_identity
from app.modules.member_switch.repository import (
    GLOBAL_SCOPE,
    ControlConflict,
    ControlRecord,
    MemberSwitchControlRepository,
    command_fingerprint,
)
from app.modules.member_switch.schemas import (
    CONTROL_PROTOCOL,
    EGO_LITE_DEVICE_AUTH_AUTOMATION_CAPABILITY,
    OWNER_MEMBERSHIP_MUTATION_CAPABILITY,
    OWNER_MEMBERSHIP_OBSERVATION_CAPABILITY,
    RECIPIENT_MEMBERSHIP_LIFECYCLE_CAPABILITY,
    Catalog,
    CommandRequest,
    CreateRunRequest,
    CurrentMember,
    Identity,
    ParticipantAction,
    ParticipantRequest,
    PreviewRequest,
    RunState,
    RunView,
    StartRequest,
)


class AuthHandoffPort(Protocol):
    def bind_catalog(self, catalog: Catalog) -> None: ...
    def validate_identity(self, identity: Identity, removed_email: str | None = None) -> None: ...
    async def prepare(
        self, request: MemberAuthHandoffPrepareRequest, *, managed_run_id: str | None = None
    ) -> MemberAuthHandoffResponse: ...
    async def advance(
        self, handoff_id: str, *, managed_run_id: str | None = None
    ) -> MemberAuthHandoffResponse | None: ...
    async def get_status(self, handoff_id: str) -> MemberAuthHandoffResponse | None: ...
    async def get_for_operation(self, operation_id: str) -> MemberAuthHandoffResponse | None: ...
    async def ensure_device_oauth_available(self, expected_flow_id: str | None = None) -> None: ...
    async def reconcile_for_operation(
        self, operation_id: str, *, managed_run_id: str | None = None
    ) -> MemberAuthHandoffResponse | None: ...
    async def observe_workspace_auth(
        self, *, workspace_id: str, workspace_account_id: str
    ) -> WorkspaceAuthObservationResponse: ...


class MemberSwitchService:
    def __init__(
        self, controls: MemberSwitchControlRepository, companion: CompanionPort, auth: AuthHandoffPort
    ) -> None:
        self.controls = controls
        self.companion = companion
        self.auth = auth

    @staticmethod
    def _decode(record: ControlRecord) -> RunState:
        if record.kind != "run":
            raise ControlConflict("record_identity_mismatch")
        try:
            state = RunState.model_validate_json(record.payload)
        except ValidationError as exc:
            raise ControlConflict("stored_run_invalid") from exc
        if state.id != record.id:
            raise ControlConflict("record_identity_mismatch")
        return state

    @classmethod
    def _view(cls, record: ControlRecord) -> RunView:
        state = cls._decode(record)
        legacy = state.control_protocol != CONTROL_PROTOCOL and state.phase != "completed"
        orphan = record.active_scope != GLOBAL_SCOPE and state.phase != "completed"
        return RunView(
            id=state.id,
            revision=record.revision,
            identity=state.identity,
            phase="needs_attention"
            if legacy or orphan
            else "outcome_unknown"
            if record.pending_action
            else state.phase,
            last_code="legacy_run_review_required" if legacy else "orphan_run_retained" if orphan else state.last_code,
            updated_at=state.updated_at,
            pending_action=record.pending_action,
            allowed_actions=[] if legacy or orphan else allowed_actions(state, record.pending_action),
            removed_email=state.preview.remove_email if state.preview else None,
            operation=state.operation,
            operation_id=state.operation_id,
            handoff_id=state.handoff_id,
            auth_state=state.auth_state,
            browser_operation_id=state.browser_operation_id,
        )

    async def get(self, run_id: str) -> RunView | None:
        record = await self.controls.get(run_id)
        return None if record is None else self._view(record)

    async def active(self) -> RunView | None:
        record = await self.controls.active()
        return None if record is None or record.kind != "run" else self._view(record)

    async def catalog(self) -> Catalog:
        return await self.companion.catalog()

    async def refresh_catalog(self) -> Catalog:
        active = await self.controls.active()
        if active is not None:
            raise ControlConflict("member_switch_catalog_refresh_requires_idle")
        admission = await self.companion.admission()
        if not admission.can_start:
            raise ControlConflict(admission.code)

        initial = await self.companion.catalog()
        if OWNER_MEMBERSHIP_OBSERVATION_CAPABILITY not in initial.capabilities:
            raise ControlConflict("companion_protocol_upgrade_required")
        observations: dict[str, tuple[list[CurrentMember], str, datetime | None]] = {}
        for workspace in initial.workspaces:
            try:
                observed = await self.companion.observe_membership(workspace.id)
            except ControlConflict as error:
                observations[workspace.id] = ([], error.code, None)
                continue
            if (
                observed.workspace_id != workspace.id
                or observed.workspace_account_id != workspace.workspace_account_id
                or observed.catalog_fingerprint != initial.catalog_fingerprint
            ):
                observations[workspace.id] = ([], "membership_observation_identity_mismatch", observed.observed_at)
                continue
            if (
                not observed.available
                or not observed.complete
                or not observed.owner_verified
                or observed.identity_ambiguous
            ):
                observations[workspace.id] = ([], observed.code, observed.observed_at)
                continue
            current = [
                CurrentMember(email=member.email, user_id=member.user_id)
                for member in observed.members
                if member.classification != "owner"
            ]
            observations[workspace.id] = (current, observed.code, observed.observed_at)

        # Membership observation may correct a known managed account's user id.
        # Read the catalog again so the returned fingerprint and switch candidates
        # describe the same post-observation identity snapshot.
        refreshed = await self.companion.catalog()
        auth_observations: dict[str, WorkspaceAuthObservationResponse | None] = {}
        try:
            self.auth.bind_catalog(refreshed)
        except ControlConflict:
            auth_observations = {workspace.id: None for workspace in refreshed.workspaces}
        else:
            for workspace in refreshed.workspaces:
                try:
                    auth_observations[workspace.id] = await self.auth.observe_workspace_auth(
                        workspace_id=workspace.id,
                        workspace_account_id=workspace.workspace_account_id,
                    )
                except Exception:
                    # Membership observation remains useful even if the local auth
                    # repository cannot be read. Do not turn an OAuth status panel
                    # failure into a false "no member" result.
                    auth_observations[workspace.id] = None

        def decorate_current_members(workspace) -> list[CurrentMember]:
            raw = observations.get(workspace.id, ([], "not_checked", None))[0]
            auth_observation = auth_observations.get(workspace.id)
            decorated: list[CurrentMember] = []
            for current in raw:
                candidates = [
                    member
                    for member in workspace.members
                    if member.email.casefold() == current.email.casefold() and member.user_id == current.user_id
                ]
                if len(candidates) != 1:
                    decorated.append(current.model_copy(update={"auth_state": "unmanaged"}))
                    continue
                candidate = candidates[0]
                if (
                    auth_observation is None
                    or not auth_observation.available
                    or auth_observation.catalog_fingerprint != refreshed.catalog_fingerprint
                ):
                    decorated.append(
                        current.model_copy(update={"preset_id": candidate.preset_id, "auth_state": "unknown"})
                    )
                    continue
                if auth_observation.identity_ambiguous:
                    decorated.append(
                        current.model_copy(update={"preset_id": candidate.preset_id, "auth_state": "ambiguous"})
                    )
                    continue
                auth_member = next(
                    (
                        member
                        for member in auth_observation.members
                        if member.preset_id == candidate.preset_id
                        and member.email.casefold() == current.email.casefold()
                        and member.user_id == current.user_id
                    ),
                    None,
                )
                decorated.append(
                    current.model_copy(
                        update={
                            "preset_id": candidate.preset_id,
                            "auth_state": auth_member.state if auth_member else "unknown",
                            "auth_account_id": auth_member.auth_account_id if auth_member else None,
                        }
                    )
                )
            return decorated

        return refreshed.model_copy(
            update={
                "workspaces": [
                    workspace.model_copy(
                        update={
                            "current_members": decorate_current_members(workspace),
                            "membership_code": observations.get(workspace.id, ([], "not_checked", None))[1],
                            "membership_observed_at": observations.get(workspace.id, ([], "not_checked", None))[2],
                        }
                    )
                    for workspace in refreshed.workspaces
                ]
            }
        )

    async def create(self, request: CreateRunRequest) -> RunView:
        run_id = str(request.run_id)
        fingerprint = command_fingerprint("create", request.model_dump_json())
        existing = await self.controls.get(run_id)
        if existing:
            if self._decode(existing).create_request_hash != fingerprint:
                raise ControlConflict("run_identity_mismatch")
            return self._view(existing)
        await require_new_work_admission(self.controls)
        catalog = await self.companion.catalog()
        required = {
            CONTROL_PROTOCOL,
            "recipient_acceptance",
            "recipient_session_readiness",
            "post_add_device_auth",
            "ego_lite_member_browser_v1",
            EGO_LITE_DEVICE_AUTH_AUTOMATION_CAPABILITY,
            OWNER_MEMBERSHIP_OBSERVATION_CAPABILITY,
            OWNER_MEMBERSHIP_MUTATION_CAPABILITY,
            RECIPIENT_MEMBERSHIP_LIFECYCLE_CAPABILITY,
            "durable_client_flow",
            "durable_participant_commands_v1",
        }
        if not catalog.enabled or not required.issubset(catalog.capabilities):
            raise ControlConflict("companion_protocol_upgrade_required")
        admission = await self.companion.admission()
        if not admission.can_start:
            raise ControlConflict(admission.code)
        workspace = next((item for item in catalog.workspaces if item.id == request.workspace_id), None)
        target = (
            next((item for item in workspace.members if item.preset_id == request.preset_id), None)
            if workspace
            else None
        )
        if not workspace or not target or catalog.catalog_fingerprint != request.catalog_fingerprint:
            raise ControlConflict("catalog_identity_mismatch")
        identity = Identity(
            workspace_id=workspace.id,
            workspace_account_id=workspace.workspace_account_id,
            preset_id=target.preset_id,
            target_email=target.email.casefold(),
            target_user_id=target.user_id,
            catalog_fingerprint=catalog.catalog_fingerprint,
        )
        self.auth.bind_catalog(catalog)
        self.auth.validate_identity(identity)
        state = RunState(
            control_protocol=CONTROL_PROTOCOL,
            id=run_id,
            identity=identity,
            create_request_hash=fingerprint,
            phase="previewed",
            last_code="preview_requested",
            updated_at=datetime.now(timezone.utc),
        )
        record = await self.controls.create(run_id, "run", state.model_dump_json(), own_scope=True)
        record, _ = await self.controls.claim(record, run_id, "preview", fingerprint, expected_revision=0)
        preview = await self.companion.preview(
            PreviewRequest(
                workspace_account_id=identity.workspace_account_id,
                preset_id=identity.preset_id,
                catalog_fingerprint=identity.catalog_fingerprint,
            )
        )
        if preview.ready and (
            preview.catalog_fingerprint != identity.catalog_fingerprint
            or preview.target_email is None
            or preview.target_email.casefold() != identity.target_email
            or preview.owner_email is None
            or preview.owner_email.casefold() != workspace.owner_email.casefold()
            or not preview.preview_token
            or preview.expires_at is None
            or preview.expires_at.tzinfo is None
            or (
                preview.remove_email
                and not any(member.email.casefold() == preview.remove_email.casefold() for member in workspace.members)
            )
        ):
            raise ControlConflict("preview_identity_mismatch")
        state = state.model_copy(
            update={"preview": preview, "last_code": preview.code, "phase": "previewed" if preview.ready else "failed"}
        )
        if preview.ready:
            self.auth.validate_identity(identity, preview.remove_email)
        return await self._save(record, state)

    async def _save(self, record: ControlRecord, state: RunState) -> RunView:
        state = state.model_copy(update={"updated_at": datetime.now(timezone.utc), "participant_request_hash": None})
        saved = await self.controls.save(
            record, state.model_dump_json(), complete=True, release=state.phase == "completed"
        )
        return self._view(saved)

    async def command(self, run_id: str, request: CommandRequest) -> RunView:
        record = await self.controls.get(run_id)
        if record is None:
            raise ControlConflict("run_not_found")
        state = self._decode(record)
        if state.control_protocol != CONTROL_PROTOCOL:
            raise ControlConflict("legacy_run_review_required")
        if record.active_scope != GLOBAL_SCOPE and state.phase != "completed":
            raise ControlConflict("orphan_run_retained")
        fingerprint = command_fingerprint(request.action, request.model_dump_json())
        if await self.controls.command_recorded(record.id, str(request.command_id), fingerprint):
            return self._view(record)
        if request.expected_revision != record.revision:
            raise ControlConflict("revision_conflict")
        if request.action not in allowed_actions(state, record.pending_action):
            raise ControlConflict("transition_not_allowed")
        if request.action == "reconcile":
            return await self._reconcile(record, state)
        # An interrupted preview never crosses a membership mutation boundary.
        if request.action == "cancel" and record.pending_action == "preview":
            return await self._save(
                record, state.model_copy(update={"phase": "completed", "last_code": "preview_cancelled"})
            )
        if request.action == "start":
            await require_new_work_admission(self.controls, owning_run_id=run_id)
            if not state.preview or not state.preview.preview_token or not state.preview.expires_at:
                raise ControlConflict("preview_required")
            if state.preview.expires_at <= datetime.now(timezone.utc):
                raise ControlConflict("preview_expired")
            current_catalog = await self.companion.catalog()
            if (
                not current_catalog.enabled
                or current_catalog.catalog_fingerprint != state.identity.catalog_fingerprint
                or not {
                    CONTROL_PROTOCOL,
                    EGO_LITE_DEVICE_AUTH_AUTOMATION_CAPABILITY,
                    OWNER_MEMBERSHIP_OBSERVATION_CAPABILITY,
                    OWNER_MEMBERSHIP_MUTATION_CAPABILITY,
                    RECIPIENT_MEMBERSHIP_LIFECYCLE_CAPABILITY,
                    "durable_client_flow",
                    "durable_participant_commands_v1",
                }.issubset(current_catalog.capabilities)
            ):
                raise ControlConflict("catalog_identity_mismatch")
            self.auth.bind_catalog(current_catalog)
            self.auth.validate_identity(state.identity, state.preview.remove_email)
            admission = await self.companion.admission()
            if not admission.can_start:
                raise ControlConflict(admission.code)
        elif request.action == "prepare_auth":
            # A new request has a new auth service. Bind the same trusted authority
            # again before claiming intent or changing any account/OAuth state.
            current_catalog = await self.companion.catalog()
            if EGO_LITE_DEVICE_AUTH_AUTOMATION_CAPABILITY not in current_catalog.capabilities:
                raise ControlConflict("companion_protocol_upgrade_required")
            self.auth.bind_catalog(current_catalog)
            self.auth.validate_identity(state.identity, state.operation.removed_email if state.operation else None)
            await self.auth.ensure_device_oauth_available()
        elif request.action == "open_browser":
            if EGO_LITE_DEVICE_AUTH_AUTOMATION_CAPABILITY not in (await self.companion.catalog()).capabilities:
                raise ControlConflict("companion_protocol_upgrade_required")
        record, execute = await self.controls.claim(
            record,
            str(request.command_id),
            request.action,
            fingerprint,
            expected_revision=request.expected_revision,
        )
        if not execute:
            return self._view(record)
        # Every path below has a committed intent. Exceptions deliberately leave
        # it pending: absence of a reply is not evidence of an absent effect.
        action = request.action
        if action == "start":
            assert state.preview is not None and state.preview.preview_token is not None
            receipt = await self.companion.start(
                StartRequest(preview_token=state.preview.preview_token, client_flow_id=state.id)
            )
            if receipt.accepted != bool(receipt.operation_id):
                raise ControlConflict("invalid_start_receipt")
            state = state.model_copy(
                update={
                    "operation_id": receipt.operation_id,
                    "phase": "membership_requested" if receipt.accepted else "failed",
                    "last_code": receipt.code,
                }
            )
        elif action == "observe_membership":
            state = await self._observe_membership(state)
        elif action in {"prepare_session", "open_browser", "close_browser"}:
            record, state = await self._participant(record, state, action)
        elif action == "prepare_auth":
            state = await self._observe_membership(state)
            if state.operation is None or not membership_confirmed(state.operation):
                return await self._save(record, state)
            auth = await self.auth.prepare(
                MemberAuthHandoffPrepareRequest(
                    member_switch_operation_id=state.operation.operation_id,
                    preset_id=state.identity.preset_id,
                    workspace_account_id=state.identity.workspace_account_id,
                    removed_email=state.operation.removed_email,
                    removed_user_id=state.operation.removed_user_id,
                    target_email=state.identity.target_email,
                    target_user_id=state.identity.target_user_id,
                    membership_state="active",
                    catalog_fingerprint=state.identity.catalog_fingerprint,
                ),
                managed_run_id=state.id,
            )
            state = self._accept_auth(state, auth)
        elif action in {"observe_auth", "advance_auth"}:
            if state.handoff_id is None:
                raise ControlConflict("handoff_missing")
            auth = (
                await self.auth.advance(state.handoff_id, managed_run_id=state.id)
                if action == "advance_auth"
                else await self.auth.get_status(state.handoff_id)
            )
            if auth is None:
                raise ControlConflict("handoff_missing")
            state = self._accept_auth(state, auth)
        elif action == "finish":
            if state.operation_id:
                finalized = await self.companion.finalize(state.operation_id)
                if not finalized.released:
                    return await self._save(record, state.model_copy(update={"last_code": finalized.code}))
            state = state.model_copy(update={"phase": "completed", "last_code": "run_finalized"})
        elif action == "cancel":
            state = state.model_copy(update={"phase": "completed", "last_code": "preview_cancelled"})
        return await self._save(record, state)

    async def _participant(
        self, record: ControlRecord, state: RunState, action: ParticipantAction
    ) -> tuple[ControlRecord, RunState]:
        operation_id = state.operation_id
        if not operation_id or not record.command_id:
            raise ControlConflict("operation_missing")
        verification_url = user_code = None
        if action == "prepare_session":
            state = await self._observe_membership(state)
            if state.operation is None or not membership_confirmed(state.operation):
                return record, state
        elif action == "open_browser":
            auth = await self.auth.get_status(state.handoff_id or "")
            if auth is None:
                raise ControlConflict("handoff_missing")
            state = self._accept_auth(state, auth)
            if (
                auth.state in {"completed", "failed"}
                or not auth.flow_id
                or not auth.user_code
                or not auth.verification_url
            ):
                raise ControlConflict("auth_browser_not_ready")
            verification_url, user_code = auth.verification_url, auth.user_code
            state = state.model_copy(update={"browser_flow_id": auth.flow_id})
        elif not state.browser_operation_id:
            raise ControlConflict("browser_missing")
        request = ParticipantRequest(
            command_id=record.command_id,
            client_flow_id=state.id,
            action=action,
            member_switch_operation_id=operation_id,
            identity=state.identity,
            browser_operation_id=state.browser_operation_id if action == "close_browser" else None,
            verification_url=verification_url,
            user_code=user_code,
        )
        state = state.model_copy(update={"participant_request_hash": participant_fingerprint(request)})
        record = await self.controls.save(record, state.model_dump_json())
        receipt = await self.companion.participant(request)
        return record, accept_participant(record, state, receipt)

    async def _observe_membership(self, state: RunState) -> RunState:
        if not state.operation_id:
            raise ControlConflict("operation_missing")
        operation = await self.companion.operation(state.operation_id)
        require_operation_identity(state.identity, state.operation_id, operation)
        phase = state.phase
        if not state.handoff_id:
            if operation.code == "operation_outcome_unknown" or operation.stage == "needs_attention":
                phase = "needs_attention"
            elif membership_confirmed(operation):
                phase = "session_prepared" if state.phase == "session_prepared" else "membership_confirmed"
            elif operation.stage == "failed":
                # An admitted operation can fail after deleting or inviting a member.
                # A failure code is not authoritative evidence that nothing changed.
                phase = "needs_attention"
            else:
                phase = "membership_requested"
        return state.model_copy(update={"operation": operation, "phase": phase, "last_code": operation.code})

    @staticmethod
    def _accept_auth(state: RunState, auth: MemberAuthHandoffResponse) -> RunState:
        identity = state.identity
        if (
            auth.member_switch_operation_id != state.operation_id
            or auth.workspace_account_id != identity.workspace_account_id
            or auth.preset_id != identity.preset_id
            or auth.target_email.casefold() != identity.target_email
            or auth.target_user_id != identity.target_user_id
            or (state.handoff_id is not None and auth.handoff_id != state.handoff_id)
        ):
            raise ControlConflict("handoff_identity_mismatch")
        if auth.pending_action:
            raise ControlConflict("handoff_outcome_unknown")
        phase = (
            "auth_confirmed"
            if auth.state == "completed"
            else "needs_attention"
            if auth.state == "failed"
            else "auth_browser_opened"
            if state.browser_operation_id
            else "needs_attention"
            if state.phase == "needs_attention"
            else "auth_prepared"
        )
        return state.model_copy(
            update={
                "handoff_id": auth.handoff_id,
                "auth_state": auth.state,
                "phase": phase,
                "last_code": "auth_browser_code_changed"
                if (
                    state.browser_operation_id
                    and state.browser_flow_id != auth.flow_id
                    and auth.state not in {"completed", "failed"}
                )
                else auth.error_code or auth.state,
            }
        )

    async def _reconcile(self, record: ControlRecord, state: RunState) -> RunView:
        """Resolve only from child receipts; never retry an unknown mutation."""
        if record.pending_action in {"prepare_session", "open_browser", "close_browser"}:
            if not record.command_id:
                raise ControlConflict("participant_command_missing")
            receipt = (
                await self.companion.reconcile_participant_receipt(record.command_id)
                if record.pending_action == "close_browser"
                else await self.companion.participant_receipt(record.command_id)
            )
            if receipt is None:
                raise ControlConflict("participant_receipt_missing")
            state = accept_participant(record, state, receipt)
        elif record.pending_action == "start":
            receipt = await self.companion.lookup(state.id)
            if not receipt or not receipt.accepted or not receipt.operation_id:
                raise ControlConflict("start_outcome_still_unknown")
            state = state.model_copy(update={"operation_id": receipt.operation_id})
            state = await self._observe_membership(state)
        elif record.pending_action == "observe_membership":
            state = await self._observe_membership(state)
        elif record.pending_action == "finish":
            receipt = await self.companion.lookup(state.id)
            if not receipt or not receipt.accepted or receipt.operation_id != state.operation_id:
                raise ControlConflict("finalization_outcome_still_unknown")
            if receipt.code == "operation_release_pending":
                assert state.operation_id is not None
                finalized = await self.companion.finalize(state.operation_id)
                if not finalized.released:
                    raise ControlConflict("finalization_outcome_still_unknown")
            elif receipt.code != "operation_finalized":
                raise ControlConflict("finalization_outcome_still_unknown")
            state = state.model_copy(update={"phase": "completed", "last_code": "run_finalized"})
        elif record.pending_action in {"prepare_auth", "advance_auth", "observe_auth"}:
            if not state.operation_id:
                raise ControlConflict("operation_missing")
            auth = (
                await self.auth.reconcile_for_operation(state.operation_id, managed_run_id=state.id)
                if record.pending_action in {"prepare_auth", "advance_auth"}
                else await self.auth.get_for_operation(state.operation_id)
            )
            if auth is None:
                raise ControlConflict("auth_outcome_still_unknown")
            if record.pending_action != "observe_auth" and auth.last_command_id != record.command_id:
                raise ControlConflict("auth_receipt_not_current")
            state = self._accept_auth(state, auth)
        else:
            raise ControlConflict("external_receipt_unavailable_manual_review_required")
        return await self._save(record, state)
