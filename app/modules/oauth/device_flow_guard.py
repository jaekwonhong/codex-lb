from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import CursorResult, update
from sqlalchemy.exc import IntegrityError

from app.db import session as db_session
from app.db.models import MemberSwitchControlRecord

OAUTH_START_GUARD_KIND = "oauth_start_guard"
OAUTH_START_GUARD_SCOPE = "member-switch"
OAUTH_START_GUARD_PROTOCOL = "oauth_start_guard_v1"


class OAuthStartGuardBusy(Exception):
    pass


class OAuthStartGuardReleaseError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class OAuthStartGuard:
    id: str
    revision: int


def _payload(*, phase: str) -> str:
    return json.dumps(
        {
            "protocol": OAUTH_START_GUARD_PROTOCOL,
            "phase": phase,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


async def acquire_oauth_start_guard() -> OAuthStartGuard:
    """Atomically reserve the shared member/OAuth start scope before external I/O."""

    row = MemberSwitchControlRecord(
        id="oauth-start:" + str(uuid4()),
        kind=OAUTH_START_GUARD_KIND,
        active_scope=OAUTH_START_GUARD_SCOPE,
        revision=0,
        payload=_payload(phase="starting"),
    )
    async with db_session.SessionLocal() as session:
        session.add(row)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise OAuthStartGuardBusy from exc
    return OAuthStartGuard(id=row.id, revision=0)


async def release_oauth_start_guard(guard: OAuthStartGuard) -> None:
    """Release only the exact guard generation acquired by this request."""

    async with db_session.SessionLocal() as session:
        result = cast(
            CursorResult[Any],
            await session.execute(
                update(MemberSwitchControlRecord)
                .where(
                    MemberSwitchControlRecord.id == guard.id,
                    MemberSwitchControlRecord.kind == OAUTH_START_GUARD_KIND,
                    MemberSwitchControlRecord.active_scope == OAUTH_START_GUARD_SCOPE,
                    MemberSwitchControlRecord.revision == guard.revision,
                )
                .values(
                    active_scope=None,
                    revision=guard.revision + 1,
                    payload=_payload(phase="completed"),
                )
            )
        )
        if int(result.rowcount or 0) != 1:
            await session.rollback()
            raise OAuthStartGuardReleaseError
        await session.commit()
