from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Account, AccountStatus
from app.modules.member_auth_handoff import rotation_events

pytestmark = pytest.mark.unit


def member_account() -> Account:
    return Account(
        id="local-thinklet09",
        email="thinklet09@gmail.com",
        chatgpt_account_id="4865cea4-fb0b-41f3-917c-b226b2acdfb0",
        chatgpt_user_id="user-9c3ymeVJZPUGcGW9iqJdXhyK",
        plan_type="team",
        access_token_encrypted="access",
        refresh_token_encrypted="refresh",
        id_token_encrypted="id",
        status=AccountStatus.ACTIVE,
    )


def second_member_account() -> Account:
    return Account(
        id="local-allnz",
        email="allnz.jk@gmail.com",
        chatgpt_account_id="4865cea4-fb0b-41f3-917c-b226b2acdfb0",
        chatgpt_user_id="user-F35N1VBxC5M3BC4LQHhamB8a",
        plan_type="team",
        access_token_encrypted="access",
        refresh_token_encrypted="refresh",
        id_token_encrypted="id",
        status=AccountStatus.ACTIVE,
    )


@pytest.mark.asyncio
async def test_two_distinct_zero_samples_create_one_claimable_event(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(rotation_events, "_path", lambda: tmp_path / "events.json")
    first = datetime.now(timezone.utc)

    needs_confirmation = await rotation_events.observe_successful_usage(member_account(), 0, first)
    await rotation_events.observe_successful_usage(member_account(), 0, first + timedelta(seconds=1))
    claimed = await rotation_events.claim_pending_event()
    duplicate = await rotation_events.claim_pending_event()

    assert needs_confirmation is True
    assert claimed is not None
    assert claimed.workspace_id == "cdp-1"
    assert claimed.preset_id == "cdp-1-thinklet09"
    assert duplicate is None
    assert claimed.claim_token is not None
    assert await rotation_events.settle_event(claimed.event_id, claimed.claim_token, processed=True)


@pytest.mark.asyncio
async def test_definitive_quota_observation_creates_one_idempotent_claimable_event(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(rotation_events, "_path", lambda: tmp_path / "events.json")
    observed_at = datetime.now(timezone.utc)
    exhausted = member_account()
    exhausted.status = AccountStatus.QUOTA_EXCEEDED
    exhausted.blocked_at = int(observed_at.timestamp())

    assert await rotation_events.observe_quota_exceeded(exhausted, observed_at)
    assert not await rotation_events.observe_quota_exceeded(
        exhausted,
        observed_at + timedelta(seconds=1),
    )

    claimed = await rotation_events.claim_pending_event()
    duplicate = await rotation_events.claim_pending_event()

    assert claimed is not None
    assert claimed.first_zero_at == observed_at.isoformat()
    assert claimed.confirmed_zero_at == observed_at.isoformat()
    assert duplicate is None


@pytest.mark.asyncio
async def test_definitive_quota_observation_requires_exact_catalog_identity(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(rotation_events, "_path", lambda: tmp_path / "events.json")
    unmatched = member_account()
    unmatched.chatgpt_user_id = "user-not-in-catalog"
    unmatched.status = AccountStatus.QUOTA_EXCEEDED
    unmatched.blocked_at = int(datetime.now(timezone.utc).timestamp())

    assert not await rotation_events.observe_quota_exceeded(
        unmatched,
        datetime.now(timezone.utc),
    )
    assert await rotation_events.claim_pending_event() is None


@pytest.mark.asyncio
async def test_positive_second_sample_clears_zero_evidence(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(rotation_events, "_path", lambda: tmp_path / "events.json")
    first = datetime.now(timezone.utc)

    await rotation_events.observe_successful_usage(member_account(), 0, first)
    await rotation_events.observe_successful_usage(member_account(), 1, first + timedelta(seconds=1))

    assert await rotation_events.claim_pending_event() is None


@pytest.mark.asyncio
async def test_duplicate_zero_timestamp_does_not_confirm_event(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(rotation_events, "_path", lambda: tmp_path / "events.json")
    observed_at = datetime.now(timezone.utc)

    assert await rotation_events.observe_successful_usage(member_account(), 0, observed_at)
    assert not await rotation_events.observe_successful_usage(member_account(), 0, observed_at)

    assert await rotation_events.claim_pending_event() is None


@pytest.mark.asyncio
async def test_released_claim_can_be_claimed_again_with_a_new_token(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(rotation_events, "_path", lambda: tmp_path / "events.json")
    first = datetime.now(timezone.utc)
    await rotation_events.observe_successful_usage(member_account(), 0, first)
    await rotation_events.observe_successful_usage(member_account(), 0, first + timedelta(seconds=1))

    claimed = await rotation_events.claim_pending_event()
    assert claimed is not None and claimed.claim_token is not None
    assert await rotation_events.settle_event(claimed.event_id, claimed.claim_token, processed=False)

    reclaimed = await rotation_events.claim_pending_event()
    assert reclaimed is not None
    assert reclaimed.event_id == claimed.event_id
    assert reclaimed.claim_token != claimed.claim_token


@pytest.mark.asyncio
async def test_released_claim_moves_behind_pending_peers(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(rotation_events, "_path", lambda: tmp_path / "events.json")
    first = datetime.now(timezone.utc)
    await rotation_events.observe_successful_usage(member_account(), 0, first)
    await rotation_events.observe_successful_usage(member_account(), 0, first + timedelta(seconds=1))
    await rotation_events.observe_successful_usage(second_member_account(), 0, first)
    await rotation_events.observe_successful_usage(second_member_account(), 0, first + timedelta(seconds=1))

    released = await rotation_events.claim_pending_event()
    assert released is not None and released.claim_token is not None
    assert await rotation_events.settle_event(released.event_id, released.claim_token, processed=False)

    peer = await rotation_events.claim_pending_event()
    assert peer is not None and peer.claim_token is not None
    assert peer.event_id != released.event_id
    assert await rotation_events.settle_event(peer.event_id, peer.claim_token, processed=True)

    reclaimed = await rotation_events.claim_pending_event()
    assert reclaimed is not None
    assert reclaimed.event_id == released.event_id


@pytest.mark.asyncio
async def test_processed_zero_event_is_not_recreated_until_positive_usage(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(rotation_events, "_path", lambda: tmp_path / "events.json")
    first = datetime.now(timezone.utc)
    await rotation_events.observe_successful_usage(member_account(), 0, first)
    await rotation_events.observe_successful_usage(member_account(), 0, first + timedelta(seconds=1))

    claimed = await rotation_events.claim_pending_event()
    assert claimed is not None and claimed.claim_token is not None
    assert await rotation_events.settle_event(claimed.event_id, claimed.claim_token, processed=True)

    await rotation_events.observe_successful_usage(member_account(), 0, first + timedelta(seconds=2))
    assert await rotation_events.claim_pending_event() is None

    await rotation_events.observe_successful_usage(member_account(), 1, first + timedelta(seconds=3))
    await rotation_events.observe_successful_usage(member_account(), 0, first + timedelta(seconds=4))
    await rotation_events.observe_successful_usage(member_account(), 0, first + timedelta(seconds=5))

    next_claim = await rotation_events.claim_pending_event()
    assert next_claim is not None
    assert next_claim.event_id != claimed.event_id


@pytest.mark.asyncio
async def test_positive_usage_invalidates_a_claimed_event_and_rearms_rotation(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(rotation_events, "_path", lambda: tmp_path / "events.json")
    first = datetime.now(timezone.utc)
    await rotation_events.observe_successful_usage(member_account(), 0, first)
    await rotation_events.observe_successful_usage(member_account(), 0, first + timedelta(seconds=1))
    claimed = await rotation_events.claim_pending_event()
    assert claimed is not None and claimed.claim_token is not None

    await rotation_events.observe_successful_usage(member_account(), 1, first + timedelta(seconds=2))

    assert not await rotation_events.settle_event(claimed.event_id, claimed.claim_token, processed=True)
    await rotation_events.observe_successful_usage(member_account(), 0, first + timedelta(seconds=3))
    await rotation_events.observe_successful_usage(member_account(), 0, first + timedelta(seconds=4))
    next_claim = await rotation_events.claim_pending_event()
    assert next_claim is not None
    assert next_claim.event_id != claimed.event_id
