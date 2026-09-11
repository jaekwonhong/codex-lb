from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Account, MemberSwitchCommandReceipt, MemberSwitchControlRecord

GLOBAL_SCOPE = "member-switch"


class ControlConflict(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ControlRecord:
    id: str
    kind: str
    active_scope: str | None
    revision: int
    payload: str
    pending_action: str | None
    command_id: str | None
    command_hash: str | None

    @classmethod
    def from_row(cls, row: MemberSwitchControlRecord) -> ControlRecord:
        return cls(
            row.id,
            row.kind,
            row.active_scope,
            row.revision,
            row.payload,
            row.pending_action,
            row.command_id,
            row.command_hash,
        )


def command_fingerprint(action: str, request: str) -> str:
    return hashlib.sha256(f"{action}\n{request}".encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class AdmissionSnapshot:
    records: tuple[ControlRecord, ...]
    quarantined_account_ids: tuple[str, ...]


class MemberSwitchControlRepository:
    """Short committed CAS transactions, shared by every request and replica.

    A pending action has no TTL. Its presence prevents replacement or replay
    after a crash. GET paths issue SELECT only and never create or repair rows.
    """

    def __init__(self, sessions: Callable[[], AsyncSession]) -> None:
        self._sessions = sessions

    async def admission_snapshot(self) -> AdmissionSnapshot:
        async with self._sessions() as session:
            rows = await session.scalars(select(MemberSwitchControlRecord).order_by(MemberSwitchControlRecord.id))
            records = tuple(ControlRecord.from_row(row) for row in rows)
            accounts = await session.scalars(
                select(Account.id)
                .where(Account.deactivation_reason == "member_auth_handoff_quarantine")
                .order_by(Account.id)
            )
            return AdmissionSnapshot(records, tuple(accounts))

    async def get(self, record_id: str) -> ControlRecord | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(MemberSwitchControlRecord).where(MemberSwitchControlRecord.id == record_id)
            )
            return None if row is None else ControlRecord.from_row(row)

    async def active(self) -> ControlRecord | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(MemberSwitchControlRecord).where(MemberSwitchControlRecord.active_scope == GLOBAL_SCOPE)
            )
            return None if row is None else ControlRecord.from_row(row)

    async def create(self, record_id: str, kind: str, payload: str, *, own_scope: bool) -> ControlRecord:
        row = MemberSwitchControlRecord(
            id=record_id,
            kind=kind,
            revision=0,
            payload=payload,
            active_scope=GLOBAL_SCOPE if own_scope else None,
        )
        async with self._sessions() as session:
            session.add(row)
            try:
                await session.flush()
                snapshot = ControlRecord.from_row(row)
                await session.commit()
                return snapshot
            except IntegrityError as exc:
                await session.rollback()
                raise ControlConflict("flow_busy_or_id_exists") from exc

    async def claim(
        self,
        current: ControlRecord,
        command_id: str,
        action: str,
        fingerprint: str,
        *,
        expected_revision: int,
    ) -> tuple[ControlRecord, bool]:
        if await self.command_recorded(current.id, command_id, fingerprint):
            return current, False
        if current.pending_action:
            raise ControlConflict("outcome_unknown")
        if current.revision != expected_revision:
            raise ControlConflict("revision_conflict")
        async with self._sessions() as session:
            result = await session.execute(
                update(MemberSwitchControlRecord)
                .where(
                    MemberSwitchControlRecord.id == current.id,
                    MemberSwitchControlRecord.revision == current.revision,
                    MemberSwitchControlRecord.pending_action.is_(None),
                )
                .values(
                    revision=current.revision + 1,
                    pending_action=action,
                    command_id=command_id,
                    command_hash=fingerprint,
                )
                .returning(MemberSwitchControlRecord)
            )
            row = result.scalar_one_or_none()
            if row is None:
                await session.rollback()
                raise ControlConflict("revision_conflict")
            snapshot = ControlRecord.from_row(row)
            session.add(
                MemberSwitchCommandReceipt(
                    record_id=current.id,
                    command_id=command_id,
                    fingerprint=fingerprint,
                )
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise ControlConflict("command_already_recorded") from exc
        return snapshot, True

    async def command_recorded(self, record_id: str, command_id: str, fingerprint: str) -> bool:
        async with self._sessions() as session:
            receipt = await session.get(MemberSwitchCommandReceipt, (record_id, command_id))
            if receipt is None:
                return False
            if receipt.fingerprint != fingerprint:
                raise ControlConflict("command_identity_mismatch")
            return True

    async def save(
        self,
        current: ControlRecord,
        payload: str,
        *,
        complete: bool = False,
        release: bool = False,
        pending_action: str | None = None,
    ) -> ControlRecord:
        async with self._sessions() as session:
            result = await session.execute(
                update(MemberSwitchControlRecord)
                .where(
                    MemberSwitchControlRecord.id == current.id,
                    MemberSwitchControlRecord.revision == current.revision,
                    MemberSwitchControlRecord.command_id == current.command_id,
                )
                .values(
                    revision=current.revision + 1,
                    payload=payload,
                    active_scope=None if release else current.active_scope,
                    pending_action=None if complete else (pending_action or current.pending_action),
                )
                .returning(MemberSwitchControlRecord)
            )
            row = result.scalar_one_or_none()
            if row is None:
                await session.rollback()
                raise ControlConflict("revision_conflict")
            snapshot = ControlRecord.from_row(row)
            await session.commit()
        return snapshot
