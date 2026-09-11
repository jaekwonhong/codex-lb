from __future__ import annotations

import asyncio
import json
import logging
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config.settings import get_settings
from app.db.models import Account, AccountStatus
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


def _path() -> Path:
    return get_settings().data_dir / "member-switch-rotation-events.json"


def _catalog():
    settings = get_settings()
    return MemberAuthHandoffCatalogRegistry(
        MemberAuthCatalogOverlayRepository(
            settings.data_dir / "member-auth-handoff-catalog.json"
        ),
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
            if item.get("identity_key") == identity_key
            and item.get("state") in {"pending", "claimed", "processed"}
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
                event_id: item
                for event_id, item in events.items()
                if item.get("identity_key") != identity_key
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
