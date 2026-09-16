from __future__ import annotations

import asyncio
import json
import logging
import secrets
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.core.utils.time import to_utc_naive, utcnow
from app.db.models import Account, AccountStatus, MemberRotationQuotaOperation
from app.db.session import sqlite_writer_section
from app.modules.member_auth_handoff.catalog import (
    PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG,
    MemberAuthHandoffCatalogEntry,
    MemberAuthHandoffCatalogRegistry,
)
from app.modules.member_auth_handoff.repository import MemberAuthCatalogOverlayRepository

_CLAIM_TTL = timedelta(seconds=30)
_RETENTION = timedelta(days=7)
_LOCK = asyncio.Lock()
logger = logging.getLogger(__name__)

_ROLLING_DAY = timedelta(hours=24)
_ROLLING_WEEK = timedelta(hours=168)
_ROLLING_DAY_LIMIT = 3
_ROLLING_WEEK_LIMIT = 7
_QUOTA_COUNT_BASIS = "observed_local"
RotationEffect = Literal["remove", "invite"]
RotationEffectOutcome = Literal["confirmed", "authoritative_non_effect"]


@dataclass(slots=True)
class RotationEvent:
    event_id: str
    workspace_id: str
    workspace_account_id: str
    preset_id: str
    email: str
    user_id: str
    catalog_fingerprint: str
    first_zero_at: str
    confirmed_zero_at: str
    state: str = "pending"
    claim_token: str | None = None
    claim_expires_at: str | None = None


@dataclass(frozen=True, slots=True)
class RotationQuotaDecision:
    admitted: bool
    code: str
    count_24h: int
    count_168h: int
    count_basis: str = _QUOTA_COUNT_BASIS
    history_complete: bool = False
    coverage_started_at: datetime | None = None


def _path() -> Path:
    return get_settings().data_dir / "member-switch-rotation-events.json"


def _catalog():
    settings = get_settings()
    return MemberAuthHandoffCatalogRegistry(
        MemberAuthCatalogOverlayRepository(settings.data_dir / "member-auth-handoff-catalog.json"),
        PACKAGED_MEMBER_AUTH_HANDOFF_CATALOG,
    ).effective_catalog()


def _identity(account: Account):
    workspace_account_id = account.chatgpt_account_id
    user_id = account.chatgpt_user_id
    if not workspace_account_id or not user_id:
        return None
    catalog = _catalog()
    matches = [
        entry
        for entry in catalog.entries
        if entry.workspace_account_id == workspace_account_id
        and entry.email.casefold() == account.email.casefold()
        and entry.user_id == user_id
    ]
    if len(matches) != 1:
        return None
    return matches[0], catalog.fingerprint()


def _load() -> dict:
    path = _path()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def _save(value: dict) -> bool:
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        return True
    except OSError:
        return False


def _key(workspace_account_id: str, email: str, user_id: str, fingerprint: str) -> str:
    return "|".join((workspace_account_id, email.casefold(), user_id, fingerprint))


def _create_event_if_missing(
    events: dict,
    *,
    identity_key: str,
    entry: MemberAuthHandoffCatalogEntry,
    fingerprint: str,
    first_zero_at: str,
    confirmed_zero_at: str,
) -> bool:
    existing = next(
        (
            item
            for item in events.values()
            if item.get("identity_key") == identity_key and item.get("state") in {"pending", "claimed", "processed"}
        ),
        None,
    )
    if existing is not None:
        return False
    event = RotationEvent(
        event_id=secrets.token_urlsafe(18),
        workspace_id=entry.workspace_id,
        workspace_account_id=entry.workspace_account_id,
        preset_id=entry.preset_id,
        email=entry.email,
        user_id=entry.user_id,
        catalog_fingerprint=fingerprint,
        first_zero_at=first_zero_at,
        confirmed_zero_at=confirmed_zero_at,
    )
    events[event.event_id] = {**asdict(event), "identity_key": identity_key}
    logger.info(
        "Member rotation event created",
        extra={
            "event_id": event.event_id,
            "workspace_id": event.workspace_id,
            "workspace_account_id": event.workspace_account_id,
            "preset_id": event.preset_id,
            "transition": "created",
        },
    )
    return True


async def observe_successful_usage(
    account: Account,
    remaining_percent: float,
    observed_at: datetime,
) -> bool:
    """Record one authoritative sample and return whether a distinct confirmation fetch is needed."""
    try:
        resolved = _identity(account)
    except Exception:
        return False
    if resolved is None:
        return False
    entry, fingerprint = resolved
    observed_at = observed_at.astimezone(timezone.utc)
    observed_text = observed_at.isoformat()
    identity_key = _key(entry.workspace_account_id, entry.email, entry.user_id, fingerprint)
    async with _LOCK:
        store = _load()
        evidence = store.setdefault("evidence", {})
        events = store.setdefault("events", {})
        current = evidence.get(identity_key)
        if remaining_percent > 0:
            evidence.pop(identity_key, None)
            store["events"] = {
                event_id: item for event_id, item in events.items() if item.get("identity_key") != identity_key
            }
            _save(store)
            return False
        if remaining_percent != 0:
            return False
        if current is None:
            evidence[identity_key] = {"first_zero_at": observed_text}
            return _save(store)
        first_zero_at = current.get("first_zero_at")
        if not isinstance(first_zero_at, str) or observed_text <= first_zero_at:
            return False
        _create_event_if_missing(
            events,
            identity_key=identity_key,
            entry=entry,
            fingerprint=fingerprint,
            first_zero_at=first_zero_at,
            confirmed_zero_at=observed_text,
        )
        _save(store)
        return False


async def observe_quota_exceeded(account: Account, observed_at: datetime) -> bool:
    """Create one rotation event from a definitive, durably persisted quota rejection."""
    if account.status != AccountStatus.QUOTA_EXCEEDED or account.blocked_at is None:
        return False
    try:
        resolved = _identity(account)
    except Exception:
        return False
    if resolved is None:
        return False
    entry, fingerprint = resolved
    observed_text = observed_at.astimezone(timezone.utc).isoformat()
    identity_key = _key(entry.workspace_account_id, entry.email, entry.user_id, fingerprint)
    async with _LOCK:
        store = _load()
        evidence = store.setdefault("evidence", {})
        events = store.setdefault("events", {})
        if not _create_event_if_missing(
            events,
            identity_key=identity_key,
            entry=entry,
            fingerprint=fingerprint,
            first_zero_at=observed_text,
            confirmed_zero_at=observed_text,
        ):
            return False
        evidence[identity_key] = {"first_zero_at": observed_text}
        return _save(store)


async def claim_pending_event() -> RotationEvent | None:
    now = datetime.now(timezone.utc)
    async with _LOCK:
        store = _load()
        events = store.setdefault("events", {})
        changed = False
        for event_id, item in list(events.items()):
            try:
                confirmed = datetime.fromisoformat(item["confirmed_zero_at"])
            except (KeyError, TypeError, ValueError):
                events.pop(event_id, None)
                changed = True
                continue
            if confirmed < now - _RETENTION:
                events.pop(event_id, None)
                changed = True
                continue
            if item.get("state") == "claimed":
                expires = item.get("claim_expires_at")
                try:
                    expired = datetime.fromisoformat(expires) <= now
                except (TypeError, ValueError):
                    expired = True
                if expired:
                    item.update(state="pending", claim_token=None, claim_expires_at=None)
                    changed = True
            if item.get("state") != "pending":
                continue
            item.update(
                state="claimed",
                claim_token=secrets.token_urlsafe(18),
                claim_expires_at=(now + _CLAIM_TTL).isoformat(),
            )
            if not _save(store):
                return None
            logger.info(
                "Member rotation event claimed",
                extra={
                    "event_id": event_id,
                    "workspace_id": item.get("workspace_id"),
                    "workspace_account_id": item.get("workspace_account_id"),
                    "preset_id": item.get("preset_id"),
                    "transition": "claimed",
                },
            )
            return RotationEvent(**{key: item.get(key) for key in RotationEvent.__dataclass_fields__})
        if changed:
            _save(store)
        return None


async def settle_event(event_id: str, claim_token: str, *, processed: bool) -> bool:
    async with _LOCK:
        store = _load()
        item = store.setdefault("events", {}).get(event_id)
        if item is None or item.get("state") != "claimed" or item.get("claim_token") != claim_token:
            return False
        if processed:
            item.update(state="processed", claim_token=None, claim_expires_at=None)
        else:
            item.update(state="pending", claim_token=None, claim_expires_at=None)
            events = store.setdefault("events", {})
            events.pop(event_id)
            events[event_id] = item
        saved = _save(store)
        if saved:
            logger.info(
                "Member rotation event settled",
                extra={
                    "event_id": event_id,
                    "workspace_id": item.get("workspace_id"),
                    "workspace_account_id": item.get("workspace_account_id"),
                    "preset_id": item.get("preset_id"),
                    "transition": "processed" if processed else "released",
                },
            )
        return saved


class RotationQuotaRepository:
    """Shared-database authority for conservative local replacement accounting.

    One request attempt produces one immutable operation identity. Admission
    reserves quota before any membership effect. Once an effect request has
    crossed the external boundary it is immediately ``unknown`` and keeps the
    reservation until authoritative evidence proves that no effect happened.
    Reservations with no confirmed effect, or with any unknown effect, stay
    counted until safely released. Confirmed effects age out from admission.
    """

    def __init__(self, session: AsyncSession, *, clock: Callable[[], datetime] | None = None) -> None:
        self._session = session
        self._clock = clock

    def _dialect_name(self) -> str:
        bind = self._session.get_bind()
        return bind.dialect.name if bind is not None else "sqlite"

    async def _now(self) -> datetime:
        if self._clock is not None:
            return to_utc_naive(self._clock())
        if self._dialect_name() == "postgresql":
            value = await self._session.scalar(text("SELECT clock_timestamp()"))
        elif self._dialect_name() == "sqlite":
            value = await self._session.scalar(text("SELECT strftime('%Y-%m-%d %H:%M:%f', 'now')"))
            if isinstance(value, str):
                value = datetime.fromisoformat(value)
        else:
            value = utcnow()
        if not isinstance(value, datetime):
            raise RuntimeError("database clock did not return a datetime")
        return to_utc_naive(value)

    async def _lock_workspace(self, workspace_account_id: str) -> None:
        await self._session.commit()
        if self._dialect_name() == "postgresql":
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": f"member_rotation_quota:{workspace_account_id}"},
            )
        elif self._dialect_name() == "sqlite":
            await self._session.execute(text("BEGIN IMMEDIATE"))

    async def _locked_operation(self, operation_id: str) -> MemberRotationQuotaOperation | None:
        if self._dialect_name() == "sqlite":
            await self._session.commit()
            await self._session.execute(text("BEGIN IMMEDIATE"))
            return await self._session.get(MemberRotationQuotaOperation, operation_id)
        stmt = select(MemberRotationQuotaOperation).where(MemberRotationQuotaOperation.operation_id == operation_id)
        if self._dialect_name() == "postgresql":
            stmt = stmt.with_for_update()
        return await self._session.scalar(stmt)

    async def _counts(
        self,
        workspace_account_id: str,
        now: datetime,
    ) -> tuple[int, int, datetime | None]:
        base = (
            MemberRotationQuotaOperation.workspace_account_id == workspace_account_id,
            MemberRotationQuotaOperation.reserved_at.is_not(None),
            MemberRotationQuotaOperation.reservation_released_at.is_(None),
            MemberRotationQuotaOperation.reserved_at <= now,
        )
        remove_unknown = MemberRotationQuotaOperation.remove_effect == "unknown"
        invite_unknown = MemberRotationQuotaOperation.invite_effect == "unknown"
        remove_confirmed = MemberRotationQuotaOperation.remove_effect == "confirmed"
        invite_confirmed = MemberRotationQuotaOperation.invite_effect == "confirmed"
        has_unknown_effect = remove_unknown | invite_unknown
        has_confirmed_effect = remove_confirmed | invite_confirmed
        confirmed_effect_metadata_invalid = (
            remove_confirmed
            & (
                MemberRotationQuotaOperation.remove_effect_at.is_(None)
                | MemberRotationQuotaOperation.remove_requested_at.is_(None)
                | (MemberRotationQuotaOperation.remove_effect_at < MemberRotationQuotaOperation.reserved_at)
                | (MemberRotationQuotaOperation.remove_effect_at < MemberRotationQuotaOperation.remove_requested_at)
            )
        ) | (
            invite_confirmed
            & (
                MemberRotationQuotaOperation.invite_effect_at.is_(None)
                | MemberRotationQuotaOperation.invite_requested_at.is_(None)
                | (MemberRotationQuotaOperation.invite_effect_at < MemberRotationQuotaOperation.reserved_at)
                | (MemberRotationQuotaOperation.invite_effect_at < MemberRotationQuotaOperation.invite_requested_at)
            )
        )
        latest_confirmed_effect_at = case(
            (
                (MemberRotationQuotaOperation.remove_effect == "confirmed")
                & (MemberRotationQuotaOperation.invite_effect == "confirmed"),
                case(
                    (
                        MemberRotationQuotaOperation.remove_effect_at >= MemberRotationQuotaOperation.invite_effect_at,
                        MemberRotationQuotaOperation.remove_effect_at,
                    ),
                    else_=MemberRotationQuotaOperation.invite_effect_at,
                ),
            ),
            (
                MemberRotationQuotaOperation.remove_effect == "confirmed",
                MemberRotationQuotaOperation.remove_effect_at,
            ),
            (
                MemberRotationQuotaOperation.invite_effect == "confirmed",
                MemberRotationQuotaOperation.invite_effect_at,
            ),
            else_=MemberRotationQuotaOperation.reserved_at,
        )
        conservative_hold = has_unknown_effect | ~has_confirmed_effect | confirmed_effect_metadata_invalid
        count_24h = int(
            await self._session.scalar(
                select(func.count(MemberRotationQuotaOperation.operation_id)).where(
                    *base,
                    conservative_hold | (latest_confirmed_effect_at > now - _ROLLING_DAY),
                )
            )
            or 0
        )
        count_168h = int(
            await self._session.scalar(
                select(func.count(MemberRotationQuotaOperation.operation_id)).where(
                    *base,
                    conservative_hold | (latest_confirmed_effect_at > now - _ROLLING_WEEK),
                )
            )
            or 0
        )
        coverage_started_at = await self._session.scalar(
            select(func.min(MemberRotationQuotaOperation.requested_at)).where(
                MemberRotationQuotaOperation.workspace_account_id == workspace_account_id
            )
        )
        return count_24h, count_168h, coverage_started_at

    async def reserve(
        self,
        *,
        operation_id: str,
        workspace_id: str,
        workspace_account_id: str,
        rotation_event_id: str | None = None,
    ) -> RotationQuotaDecision:
        async with sqlite_writer_section():
            await self._lock_workspace(workspace_account_id)
            now = await self._now()
            existing = await self._session.get(MemberRotationQuotaOperation, operation_id)
            if existing is None and rotation_event_id is not None:
                existing_event = await self._session.scalar(
                    select(MemberRotationQuotaOperation).where(
                        MemberRotationQuotaOperation.rotation_event_id == rotation_event_id
                    )
                )
                if existing_event is not None:
                    await self._session.rollback()
                    raise ValueError("rotation event is already bound to another quota operation")
            if existing is not None:
                if (
                    existing.workspace_id != workspace_id
                    or existing.workspace_account_id != workspace_account_id
                    or existing.rotation_event_id != rotation_event_id
                ):
                    await self._session.rollback()
                    raise ValueError("rotation quota operation identity mismatch")
                count_24h, count_168h, coverage_started_at = await self._counts(workspace_account_id, now)
                if existing.reservation_released_at is not None:
                    await self._session.rollback()
                    return RotationQuotaDecision(
                        admitted=False,
                        code="reservation_released",
                        count_24h=count_24h,
                        count_168h=count_168h,
                        coverage_started_at=coverage_started_at,
                    )
                if existing.completed_at is not None:
                    await self._session.rollback()
                    return RotationQuotaDecision(
                        admitted=False,
                        code="operation_completed",
                        count_24h=count_24h,
                        count_168h=count_168h,
                        coverage_started_at=coverage_started_at,
                    )
                if existing.reserved_at is None:
                    admitted = count_24h < _ROLLING_DAY_LIMIT and count_168h < _ROLLING_WEEK_LIMIT
                    code = (
                        "admitted"
                        if admitted
                        else "rolling_24h_limit"
                        if count_24h >= _ROLLING_DAY_LIMIT
                        else "rolling_168h_limit"
                    )
                    if admitted:
                        existing.reserved_at = now
                        await self._session.commit()
                    else:
                        await self._session.rollback()
                    return RotationQuotaDecision(
                        admitted=admitted,
                        code=code,
                        count_24h=count_24h + int(admitted),
                        count_168h=count_168h + int(admitted),
                        coverage_started_at=coverage_started_at,
                    )
                await self._session.rollback()
                return RotationQuotaDecision(
                    admitted=True,
                    code="admitted",
                    count_24h=count_24h,
                    count_168h=count_168h,
                    coverage_started_at=coverage_started_at,
                )

            count_24h, count_168h, coverage_started_at = await self._counts(workspace_account_id, now)
            admitted = count_24h < _ROLLING_DAY_LIMIT and count_168h < _ROLLING_WEEK_LIMIT
            code = (
                "admitted"
                if admitted
                else "rolling_24h_limit"
                if count_24h >= _ROLLING_DAY_LIMIT
                else "rolling_168h_limit"
            )
            row = MemberRotationQuotaOperation(
                operation_id=operation_id,
                workspace_id=workspace_id,
                workspace_account_id=workspace_account_id,
                rotation_event_id=rotation_event_id,
                requested_at=now,
                initial_admission_code=code,
                reserved_at=now if admitted else None,
            )
            self._session.add(row)
            await self._session.commit()
        return RotationQuotaDecision(
            admitted=admitted,
            code=code,
            count_24h=count_24h + int(admitted),
            count_168h=count_168h + int(admitted),
            coverage_started_at=coverage_started_at or now,
        )

    async def snapshot(
        self,
        *,
        workspace_account_id: str,
        observed_at: datetime,
    ) -> RotationQuotaDecision:
        now = to_utc_naive(observed_at)
        count_24h, count_168h, coverage_started_at = await self._counts(workspace_account_id, now)
        return RotationQuotaDecision(
            admitted=count_24h < _ROLLING_DAY_LIMIT and count_168h < _ROLLING_WEEK_LIMIT,
            code=(
                "admitted"
                if count_24h < _ROLLING_DAY_LIMIT and count_168h < _ROLLING_WEEK_LIMIT
                else "rolling_24h_limit"
                if count_24h >= _ROLLING_DAY_LIMIT
                else "rolling_168h_limit"
            ),
            count_24h=count_24h,
            count_168h=count_168h,
            coverage_started_at=coverage_started_at,
        )

    async def record_effect_request(
        self,
        operation_id: str,
        *,
        effect: RotationEffect,
    ) -> MemberRotationQuotaOperation:
        async with sqlite_writer_section():
            row = await self._locked_operation(operation_id)
            if row is None or row.reserved_at is None:
                await self._session.rollback()
                raise ValueError("rotation quota reservation missing")
            effect_field = f"{effect}_effect"
            requested_field = f"{effect}_requested_at"
            state = getattr(row, effect_field)
            requested = getattr(row, requested_field)
            if row.reservation_released_at is not None:
                await self._session.rollback()
                raise ValueError("rotation quota operation is terminal")
            if row.completed_at is not None:
                # Crash recovery may re-observe a boundary that was durably
                # recorded before the quota row became terminal.  Treat that
                # exact replay as an idempotent read, but never let terminal
                # state create a new effect boundary.
                if state != "not_attempted" and requested is not None:
                    await self._session.rollback()
                    replay = await self._session.get(MemberRotationQuotaOperation, operation_id)
                    assert replay is not None
                    return replay
                await self._session.rollback()
                raise ValueError("rotation quota operation is terminal")
            requested_at = await self._now()
            if state == "not_attempted":
                setattr(row, requested_field, requested_at)
                setattr(row, effect_field, "unknown")
            elif requested is None:
                await self._session.rollback()
                raise ValueError("rotation effect state missing request boundary")
            await self._session.commit()
            await self._session.refresh(row)
            return row

    async def record_effect_outcome(
        self,
        operation_id: str,
        *,
        effect: RotationEffect,
        outcome: RotationEffectOutcome,
    ) -> MemberRotationQuotaOperation:
        async with sqlite_writer_section():
            row = await self._locked_operation(operation_id)
            if row is None or row.reserved_at is None:
                await self._session.rollback()
                raise ValueError("rotation quota reservation missing")
            effect_field = f"{effect}_effect"
            effect_at_field = f"{effect}_effect_at"
            requested_field = f"{effect}_requested_at"
            state = getattr(row, effect_field)
            requested = getattr(row, requested_field)
            effect_at = getattr(row, effect_at_field)
            if row.reservation_released_at is not None or row.completed_at is not None:
                # A controller can crash after quota terminalization but before
                # publishing the matching controller state.  Replaying the
                # already-recorded outcome is safe and lets restart reconciliation
                # converge without reopening quota or changing history.
                if state == outcome and requested is not None and effect_at is not None:
                    await self._session.rollback()
                    replay = await self._session.get(MemberRotationQuotaOperation, operation_id)
                    assert replay is not None
                    return replay
                await self._session.rollback()
                raise ValueError("rotation quota operation is terminal")
            observed_at = await self._now()
            if requested is None or state == "not_attempted":
                await self._session.rollback()
                raise ValueError("rotation effect boundary was not recorded")
            if state == "unknown":
                setattr(row, effect_field, outcome)
                setattr(row, effect_at_field, observed_at)
            elif state != outcome:
                await self._session.rollback()
                raise ValueError("contradictory rotation effect outcome")
            await self._session.commit()
            await self._session.refresh(row)
            return row

    async def require_effect_request_open(
        self,
        operation_id: str,
        *,
        effect: RotationEffect,
    ) -> MemberRotationQuotaOperation:
        """Fail closed unless a reserved, non-terminal effect boundary is still open.

        This is a pre-effect liveness check only.  It does not record an effect
        request and therefore never grants membership mutation authority.
        """
        async with sqlite_writer_section():
            row = await self._locked_operation(operation_id)
            if row is None or row.reserved_at is None:
                await self._session.rollback()
                raise ValueError("rotation quota reservation missing")
            if row.reservation_released_at is not None or row.completed_at is not None:
                await self._session.rollback()
                raise ValueError("rotation quota operation is terminal")
            state = getattr(row, f"{effect}_effect")
            requested = getattr(row, f"{effect}_requested_at")
            if state != "not_attempted" or requested is not None:
                await self._session.rollback()
                raise ValueError("rotation effect boundary already recorded")
            await self._session.rollback()
            current = await self._session.get(MemberRotationQuotaOperation, operation_id)
            assert current is not None
            return current

    async def mark_completed(
        self,
        operation_id: str,
    ) -> MemberRotationQuotaOperation:
        async with sqlite_writer_section():
            row = await self._locked_operation(operation_id)
            if row is None or row.reserved_at is None:
                await self._session.rollback()
                raise ValueError("rotation quota reservation missing")
            if row.reservation_released_at is not None:
                await self._session.rollback()
                raise ValueError("rotation quota reservation was released")
            if row.remove_effect == "unknown" or row.invite_effect == "unknown":
                await self._session.rollback()
                raise ValueError("rotation quota operation has unresolved effect")
            if row.remove_effect != "confirmed" and row.invite_effect != "confirmed":
                await self._session.rollback()
                raise ValueError("rotation quota operation has no confirmed effect")
            completed_at = await self._now()
            if row.completed_at is None:
                row.completed_at = completed_at
            await self._session.commit()
            await self._session.refresh(row)
            return row

    async def release_reservation(
        self,
        operation_id: str,
    ) -> bool:
        """Return quota only while every crossed effect is authoritatively absent."""
        async with sqlite_writer_section():
            row = await self._locked_operation(operation_id)
            if row is None or row.reserved_at is None:
                await self._session.rollback()
                return False
            if row.reservation_released_at is not None:
                await self._session.rollback()
                return True
            if row.completed_at is not None:
                await self._session.rollback()
                return False
            for effect in ("remove", "invite"):
                state = getattr(row, f"{effect}_effect")
                requested = getattr(row, f"{effect}_requested_at")
                if state in {"unknown", "confirmed"}:
                    await self._session.rollback()
                    return False
                if requested is not None and state != "authoritative_non_effect":
                    await self._session.rollback()
                    return False
            released_at = await self._now()
            row.reservation_released_at = released_at
            await self._session.commit()
            return True
