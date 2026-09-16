from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.core.usage import normalize_rate_limit_windows
from app.core.usage.models import RateLimitPayload, UsagePayload, UsageWindow
from app.core.usage.refresh_policy import usage_freshness_horizon_seconds
from app.core.usage.weekly_observation import (
    UsageAccountIdentity,
    UsageFetchProvenance,
    WeeklyUsageObservation,
    five_hour_window_from_payload,
    weekly_window_from_payload,
)

pytestmark = pytest.mark.unit
NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)
RESET = int(NOW.timestamp()) + 3600
MEMBER = UsageAccountIdentity("local-seat-a", "upstream-workspace-a", "user-a", "member@example.com")


def _window(seconds: int | None = 604800, used: float | None = 100.0) -> UsageWindow:
    return UsageWindow(used_percent=used, limit_window_seconds=seconds, reset_at=RESET)


def _observation(rate_limit: RateLimitPayload | None) -> WeeklyUsageObservation:
    payload = UsagePayload(rate_limit=rate_limit)
    return WeeklyUsageObservation(
        fetch_succeeded=True,
        usage_written=False,
        provenance=UsageFetchProvenance(
            fetch_id="fetch-a",
            identity=MEMBER,
            requested_workspace_account_id=MEMBER.workspace_account_id,
            account_workspace_id="metadata-workspace-a",
            payload_workspace_id="metadata-workspace-a",
            credential_source="stored",
            started_at=NOW - timedelta(seconds=1),
            observed_at=NOW,
        ),
        window=weekly_window_from_payload(payload, observed_at=NOW),
    )


@pytest.mark.parametrize(
    ("primary", "secondary", "slot"),
    [
        (_window(18000), _window(), "secondary"),
        (_window(), None, "primary"),
        (None, _window(), "secondary"),
        (_window(), UsageWindow(used_percent=0), "primary"),
        (UsageWindow(used_percent=0), _window(), "secondary"),
        (_window(), _window(18000), "primary"),
        (_window(604799), None, "primary"),
    ],
)
def test_weekly_uses_window_metadata_and_preserves_source_slot(primary, secondary, slot) -> None:
    observation = _observation(RateLimitPayload(primary_window=primary, secondary_window=secondary))
    assert observation.assess(MEMBER, now=NOW).state == "exhausted"
    assert observation.window is not None
    assert observation.window.source_slot == slot
    assert observation.window.raw_used_percent == 100.0
    assert observation.window.window_minutes == 10080
    assert observation.window.reset_at == RESET
    assert observation.provenance is not None
    assert observation.provenance.observed_at == NOW
    assert observation.provenance.fetch_id == "fetch-a"
    if secondary is None and primary is not None:
        assert normalize_rate_limit_windows(primary, secondary).primary is primary


@pytest.mark.parametrize(
    "rate_limit",
    [
        None,
        RateLimitPayload(),
        RateLimitPayload(primary_window=_window(18000)),
        RateLimitPayload(secondary_window=_window(18000)),
        RateLimitPayload(primary_window=_window(2592000)),
        RateLimitPayload(secondary_window=_window(2592000)),
        RateLimitPayload(primary_window=UsageWindow(used_percent=0)),
        RateLimitPayload(secondary_window=UsageWindow(used_percent=100)),
        RateLimitPayload(primary_window=_window(None)),
        RateLimitPayload(primary_window=_window(0)),
        RateLimitPayload(primary_window=_window(-1)),
        RateLimitPayload(primary_window=_window(604740)),
    ],
)
def test_non_weekly_missing_and_placeholder_windows_are_unknown(rate_limit) -> None:
    observation = _observation(rate_limit)
    assert observation.window is None
    assert observation.assess(MEMBER, now=NOW).state == "unknown"


@pytest.mark.parametrize(
    ("used", "state"),
    [
        (0, "available"),
        (99.49, "available"),
        (99.51, "available"),
        (99.999999, "available"),
        (100, "exhausted"),
        (100.01, "exhausted"),
        (None, "unknown"),
        (-1, "unknown"),
        (float("nan"), "unknown"),
        (float("inf"), "unknown"),
        (float("-inf"), "unknown"),
    ],
)
def test_exhaustion_uses_raw_numeric_value(used, state) -> None:
    observation = _observation(RateLimitPayload(secondary_window=_window(used=used)))
    assert observation.assess(MEMBER, now=NOW).state == state
    if used == 99.999999:
        assert round(100 - used) == 0
        assert observation.window is not None
        assert observation.window.raw_used_percent is not None
        assert observation.window.raw_used_percent < 100


@pytest.mark.parametrize("reset", [None, int(NOW.timestamp()) - 1, int(NOW.timestamp())])
def test_missing_or_elapsed_reset_never_reuses_exhaustion(reset) -> None:
    window = _window()
    window.reset_at = reset
    observation = _observation(RateLimitPayload(primary_window=window))
    assert observation.assess(MEMBER, now=NOW).state == "unknown"


def test_assessment_rechecks_reset_at_consumption_time() -> None:
    window = _window()
    window.reset_at = int(NOW.timestamp()) + 10
    observation = _observation(RateLimitPayload(primary_window=window))
    assert observation.assess(MEMBER, now=NOW).state == "exhausted"
    assert observation.assess(MEMBER, now=NOW + timedelta(seconds=10)).reason == "reset_elapsed"
    assert observation.window is not None and observation.window.raw_used_percent == 100
    fresh = _observation(RateLimitPayload(primary_window=_window(used=0)))
    assert fresh.provenance is not None
    fresh = replace(
        fresh,
        provenance=replace(
            fresh.provenance,
            fetch_id="fetch-after-reset",
            started_at=NOW + timedelta(seconds=10),
            observed_at=NOW + timedelta(seconds=11),
        ),
    )
    assert fresh.assess(MEMBER, now=NOW + timedelta(seconds=11)).state == "available"


def test_relative_reset_uses_observation_time() -> None:
    window = UsageWindow(used_percent=100, limit_window_seconds=604800, reset_after_seconds=60)
    observation = _observation(RateLimitPayload(primary_window=window))
    assert observation.window is not None
    assert observation.window.reset_at == int(NOW.timestamp()) + 60
    assert observation.assess(MEMBER, now=NOW).state == "exhausted"


def test_two_real_weekly_windows_reuse_reset_precedence() -> None:
    primary, secondary = _window(used=100), _window(used=40)
    secondary.reset_at = RESET + 60
    observation = _observation(RateLimitPayload(primary_window=primary, secondary_window=secondary))
    assert observation.window is not None and observation.window.source_slot == "secondary"
    assert observation.assess(MEMBER, now=NOW).state == "available"


@pytest.mark.parametrize("written", [False, True])
def test_fetch_success_and_write_result_are_independent(written: bool) -> None:
    observation = replace(_observation(RateLimitPayload(primary_window=_window())), usage_written=written)
    assert observation.assess(MEMBER, now=NOW).state == "exhausted"
    assert replace(observation, fetch_succeeded=False).assess(MEMBER, now=NOW).state == "unknown"


def test_success_flag_without_actual_fetch_provenance_is_unknown() -> None:
    observation = replace(_observation(RateLimitPayload(primary_window=_window())), provenance=None)
    assert observation.assess(MEMBER, now=NOW).reason == "fetch_not_observed"


@pytest.mark.parametrize(
    "current_member",
    [
        replace(MEMBER, account_id="another-local-slot"),
        replace(MEMBER, workspace_account_id="another-workspace"),
        replace(MEMBER, user_id="another-user"),
        replace(MEMBER, email="another@example.com"),
        replace(MEMBER, workspace_account_id=None),
        replace(MEMBER, user_id=None),
    ],
)
def test_exact_account_workspace_and_principal_binding(current_member) -> None:
    observation = _observation(RateLimitPayload(primary_window=_window()))
    assert observation.assess(current_member, now=NOW).reason == "identity_mismatch"


@pytest.mark.parametrize("identity", [replace(MEMBER, user_id=None), replace(MEMBER, user_id=" ")])
def test_matching_incomplete_identities_are_not_proof(identity) -> None:
    observation = _observation(RateLimitPayload(primary_window=_window()))
    assert observation.provenance is not None
    observation = replace(observation, provenance=replace(observation.provenance, identity=identity))
    assert observation.assess(identity, now=NOW).state == "unknown"


@pytest.mark.parametrize(
    "changes",
    [
        {"payload_workspace_id": "wrong-workspace"},
        {"requested_workspace_account_id": "wrong-header"},
        {"requested_workspace_account_id": None},
        {"credential_source": "override"},
    ],
)
def test_unverified_fetch_identity_is_unknown(changes) -> None:
    observation = _observation(RateLimitPayload(primary_window=_window()))
    assert observation.provenance is not None
    observation = replace(observation, provenance=replace(observation.provenance, **changes))
    assert observation.assess(MEMBER, now=NOW).state == "unknown"


def test_same_email_casing_and_workspace_less_payload_preserve_token_binding() -> None:
    observation = _observation(RateLimitPayload(primary_window=_window()))
    assert observation.provenance is not None
    observation = replace(observation, provenance=replace(observation.provenance, payload_workspace_id=None))
    assert observation.assess(replace(MEMBER, email=MEMBER.email.upper()), now=NOW).state == "exhausted"


def test_age_future_clock_and_fetch_start_boundary() -> None:
    observation = _observation(RateLimitPayload(primary_window=_window()))
    assert observation.assess(MEMBER, now=NOW - timedelta(microseconds=1)).reason == "invalid_fetch_time"
    assert observation.assess(MEMBER, now=NOW, not_before=NOW).reason == "fetch_before_boundary"
    assert observation.assess(MEMBER, now=NOW, not_before=NOW - timedelta(seconds=1)).state == "exhausted"
    assert observation.assess(MEMBER, now=NOW + timedelta(seconds=usage_freshness_horizon_seconds())).reason == "stale"
    assert observation.assess(MEMBER, now=NOW.replace(tzinfo=None)).state == "exhausted"


@pytest.mark.parametrize("slot", ["primary", "secondary"])
def test_five_hour_classification_uses_duration_not_slot(slot: str) -> None:
    five_hour = _window(18000, used=17.5)
    payload = UsagePayload(
        rate_limit=RateLimitPayload(
            primary_window=five_hour if slot == "primary" else _window(),
            secondary_window=five_hour if slot == "secondary" else _window(),
        )
    )
    observed = five_hour_window_from_payload(payload, observed_at=NOW)
    assert observed is not None
    assert observed.source_slot == slot
    assert observed.raw_used_percent == 17.5
    assert observed.window_minutes == 300
    assert observed.reset_at == RESET


def test_two_five_hour_shaped_slots_are_ambiguous_for_retention() -> None:
    payload = UsagePayload(
        rate_limit=RateLimitPayload(
            primary_window=_window(18000, used=10),
            secondary_window=_window(18000, used=20),
        )
    )
    assert five_hour_window_from_payload(payload, observed_at=NOW) is None
