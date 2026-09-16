from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils.time import utcnow
from app.db.models import MemberRotationQuotaOperation, MemberRotationWorkspaceControl


class RotationIntentConflict(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RotationIntentRecord:
    workspace_id: str
    workspace_account_id: str
    enabled: bool
    version: int
    updated_at: datetime | None


class MemberRotationOperatorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def intent(self, *, workspace_id: str, workspace_account_id: str) -> RotationIntentRecord:
        row = await self._session.get(MemberRotationWorkspaceControl, workspace_id)
        if row is None:
            return RotationIntentRecord(
                workspace_id=workspace_id,
                workspace_account_id=workspace_account_id,
                enabled=False,
                version=0,
                updated_at=None,
            )
        if row.workspace_account_id != workspace_account_id:
            raise RotationIntentConflict("workspace identity changed for stored rotation control")
        return RotationIntentRecord(
            workspace_id=row.workspace_id,
            workspace_account_id=row.workspace_account_id,
            enabled=row.automatic_rotation_enabled,
            version=row.version,
            updated_at=row.updated_at,
        )

    async def set_intent(
        self,
        *,
        workspace_id: str,
        workspace_account_id: str,
        enabled: bool,
        expected_version: int,
    ) -> RotationIntentRecord:
        current = await self._session.get(MemberRotationWorkspaceControl, workspace_id)
        if current is None:
            if expected_version != 0:
                raise RotationIntentConflict("rotation intent changed; reload before saving")
            row = MemberRotationWorkspaceControl(
                workspace_id=workspace_id,
                workspace_account_id=workspace_account_id,
                automatic_rotation_enabled=enabled,
                version=1,
            )
            self._session.add(row)
            try:
                await self._session.commit()
            except IntegrityError as exc:
                await self._session.rollback()
                raise RotationIntentConflict("rotation intent changed; reload before saving") from exc
            await self._session.refresh(row)
            return RotationIntentRecord(
                workspace_id=row.workspace_id,
                workspace_account_id=row.workspace_account_id,
                enabled=row.automatic_rotation_enabled,
                version=row.version,
                updated_at=row.updated_at,
            )

        if current.workspace_account_id != workspace_account_id:
            raise RotationIntentConflict("workspace identity changed for stored rotation control")
        if current.version != expected_version:
            raise RotationIntentConflict("rotation intent changed; reload before saving")
        next_version = expected_version + 1
        result = await self._session.execute(
            update(MemberRotationWorkspaceControl)
            .where(
                MemberRotationWorkspaceControl.workspace_id == workspace_id,
                MemberRotationWorkspaceControl.workspace_account_id == workspace_account_id,
                MemberRotationWorkspaceControl.version == expected_version,
            )
            .values(
                automatic_rotation_enabled=enabled,
                version=next_version,
                updated_at=utcnow(),
            )
            .execution_options(synchronize_session=False)
        )
        if (getattr(result, "rowcount", 0) or 0) != 1:
            await self._session.rollback()
            raise RotationIntentConflict("rotation intent changed; reload before saving")
        await self._session.commit()
        row = await self._session.get(MemberRotationWorkspaceControl, workspace_id)
        if row is None:
            raise RuntimeError("rotation intent disappeared after update")
        return RotationIntentRecord(
            workspace_id=row.workspace_id,
            workspace_account_id=row.workspace_account_id,
            enabled=row.automatic_rotation_enabled,
            version=row.version,
            updated_at=row.updated_at,
        )

    async def unresolved_effect_codes(self, *, workspace_account_id: str) -> tuple[str, ...]:
        rows = list(
            (
                await self._session.scalars(
                    select(MemberRotationQuotaOperation)
                    .where(
                        MemberRotationQuotaOperation.workspace_account_id == workspace_account_id,
                        MemberRotationQuotaOperation.reservation_released_at.is_(None),
                    )
                    .order_by(MemberRotationQuotaOperation.requested_at.desc())
                )
            ).all()
        )
        codes: list[str] = []
        if any(row.remove_effect == "unknown" for row in rows):
            codes.append("unknown_remove_effect")
        if any(row.invite_effect == "unknown" for row in rows):
            codes.append("unknown_invite_effect")
        return tuple(codes)
