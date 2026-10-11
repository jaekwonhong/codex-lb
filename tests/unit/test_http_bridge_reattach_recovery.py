from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.openai.requests import ResponsesRequest
from app.db.models import HttpBridgeOperationRecord
from app.modules.proxy._service.http_bridge.reattach_recovery import rebuild_verified_fresh_reattach
from app.modules.proxy.durable_bridge_repository import DurableBridgeRepository


@dataclass(frozen=True)
class _Operation:
    request_text: str
    response_id: str = "resp_owner"
    parent_response_id: str | None = None
    state: str = "completed"
    event_spool_complete: bool = True
    session_id: str = "durable-owner"
    account_id: str = "acc-owner"


@dataclass(frozen=True)
class _Turn:
    operation: _Operation
    events: tuple[str, ...]


def _user(text: str) -> dict[str, object]:
    return {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}


def _answer(text: str) -> dict[str, object]:
    return {
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text}],
    }


def _turn() -> _Turn:
    return _Turn(
        operation=_Operation(
            request_text=json.dumps(
                {"type": "response.create", "model": "gpt-6.1-sol", "input": [_user("prior question")]},
                separators=(",", ":"),
            ),
        ),
        events=(
            "event: response.completed\ndata: "
            + json.dumps(
                {
                    "type": "response.completed",
                    "response": {"id": "resp_owner", "output": [_answer("prior answer")]},
                },
                separators=(",", ":"),
            )
            + "\n\n",
        ),
    )


def _payload(**overrides: object) -> ResponsesRequest:
    return ResponsesRequest.model_validate(
        {"model": "gpt-6.1-sol", "instructions": "test", "input": [_user("follow-up")], **overrides}
    )


def _rebuild(
    *,
    payload: ResponsesRequest | None = None,
    transcript: list[_Turn] | None = None,
    response_id: str = "resp_owner",
    account_id: str = "acc-owner",
    session_id: str = "durable-owner",
) -> ResponsesRequest | None:
    return rebuild_verified_fresh_reattach(
        payload=payload or _payload(),
        response_id=response_id,
        owner_account_id=account_id,
        durable_session_id=session_id,
        transcript=[_turn()] if transcript is None else transcript,
    )


def test_same_owner_completed_context_reconstructed_without_old_socket_anchor() -> None:
    payload = _payload()
    recovered = _rebuild(payload=payload)
    assert recovered is not None
    assert recovered.model == payload.model
    assert recovered.previous_response_id is None
    assert recovered.input == [_user("prior question"), _answer("prior answer"), _user("follow-up")]
    assert payload.previous_response_id is None
    assert payload.input == [_user("follow-up")]


@pytest.mark.parametrize(
    ("changed", "reason"),
    [
        ({"response_id": "resp_foreign"}, "anchor mismatch"),
        ({"session_id": "durable-other"}, "session mismatch"),
        ({"account_id": "acc-other"}, "owner mismatch"),
        ({"state": "incomplete"}, "incomplete prior answer"),
        ({"state": "submitted"}, "ambiguous prior execution"),
        ({"event_spool_complete": False}, "truncated event spool"),
        ({"parent_response_id": "resp_orphan"}, "broken parent chain"),
        ({"request_text": ""}, "missing request body"),
    ],
)
def test_origin_or_completed_transcript_proof_failure_does_not_replay(changed: dict[str, object], reason: str) -> None:
    del reason
    original = _turn()
    changed_turn = replace(original, operation=replace(original.operation, **changed))
    assert _rebuild(transcript=[changed_turn]) is None


def test_unavailable_or_truncated_output_fails_closed() -> None:
    original = _turn()
    assert _rebuild(transcript=[]) is None
    assert _rebuild(transcript=[replace(original, events=())]) is None
    assert _rebuild(transcript=[replace(original, events=("event: response.created\ndata: {}\n\n",))]) is None


@pytest.mark.parametrize("terminal_type", ["response.incomplete", "response.failed"])
def test_non_completed_upstream_terminal_is_not_reconstructed_even_if_row_claims_completed(
    terminal_type: str,
) -> None:
    original = _turn()
    substituted = replace(
        original,
        events=(
            "data: "
            + json.dumps(
                {
                    "type": terminal_type,
                    "response": {"id": "resp_owner", "output": [_answer("unsafe partial answer")]},
                }
            )
            + "\n\n",
        ),
    )
    assert _rebuild(transcript=[substituted]) is None


def test_completed_response_event_must_match_durable_operation_id() -> None:
    original = _turn()
    foreign = replace(
        original,
        events=(
            "data: "
            + json.dumps(
                {
                    "type": "response.completed",
                    "response": {"id": "resp_foreign", "output": [_answer("foreign conversation")]},
                }
            )
            + "\n\n",
        ),
    )
    assert _rebuild(transcript=[foreign]) is None


@pytest.mark.parametrize("second_terminal_type", ["response.completed", "response.failed", "response.incomplete"])
def test_matching_terminal_followed_by_conflicting_terminal_cannot_rebuild(
    second_terminal_type: str,
) -> None:
    original = _turn()
    appended = replace(
        original,
        events=(
            *original.events,
            "data: "
            + json.dumps(
                {
                    "type": second_terminal_type,
                    "response": {"id": "resp_foreign", "output": [_answer("foreign answer")]},
                },
            )
            + "\n\n",
        ),
    )
    assert _rebuild(transcript=[appended]) is None


def test_earlier_transcript_turn_from_another_owner_is_rejected() -> None:
    original = _turn()
    older = replace(
        original,
        operation=replace(original.operation, response_id="resp_older", account_id="acc-other"),
        events=(
            "data: "
            + json.dumps(
                {
                    "type": "response.completed",
                    "response": {"id": "resp_older", "output": [_answer("foreign answer")]},
                }
            )
            + "\n\n",
        ),
    )
    newer = replace(
        original,
        operation=replace(original.operation, parent_response_id="resp_older"),
    )
    assert _rebuild(transcript=[older, newer]) is None


def test_client_supplied_anchor_never_replaced() -> None:
    assert _rebuild(payload=_payload(previous_response_id="resp_owner")) is None
    assert _rebuild(payload=_payload(conversation="conv_other")) is None


def test_response_owned_encrypted_reasoning_is_stripped_from_rebuilt_context() -> None:
    original = _turn()
    unsafe = replace(
        original,
        operation=replace(
            original.operation,
            request_text=json.dumps(
                {
                    "type": "response.create",
                    "model": "gpt-6.1-sol",
                    "input": [
                        _user("prior question"),
                        {"type": "reasoning", "encrypted_content": "secret"},
                    ],
                }
            ),
        ),
    )
    rebuilt = _rebuild(transcript=[unsafe])
    assert rebuilt is not None
    assert "encrypted_content" not in json.dumps(rebuilt.input)
    assert rebuilt.input == [_user("prior question"), _answer("prior answer"), _user("follow-up")]


def test_cannot_replay_client_file_or_hosted_account_reference() -> None:
    assert (
        _rebuild(
            payload=_payload(
                input=[{"type": "message", "role": "user", "content": [{"type": "input_file", "file_id": "file_1"}]}]
            )
        )
        is None
    )


def test_bounded_transcript_rejects_oversize_without_dispatch() -> None:
    original = _turn()
    oversized = replace(
        original,
        operation=replace(
            original.operation,
            request_text=json.dumps(
                {
                    "type": "response.create",
                    "model": "gpt-6.1-sol",
                    "input": [_user("x" * (8 * 1024 * 1024 + 16))],
                }
            ),
        ),
    )
    assert _rebuild(transcript=[oversized]) is None


def test_broken_complete_chain_rejected_without_retransmission() -> None:
    original = _turn()
    older = replace(original, operation=replace(original.operation, response_id="resp_older"))
    newer = replace(original, operation=replace(original.operation, parent_response_id="resp_wrong"))
    assert _rebuild(transcript=[older, newer]) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("intervening_state", ["incomplete", "unknown", "failed", "completed"])
@pytest.mark.parametrize("older_created", [False, True], ids=["new-operation", "old-retried-operation"])
async def test_uninterrupted_head_query_rejects_newer_operation_of_any_state(
    intervening_state: str,
    older_created: bool,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(HttpBridgeOperationRecord.__table__.create)
        now = datetime.now(UTC)
        rows = [
            {
                "operation_id": "op_prior_completed",
                "session_id": "durable-owner",
                "request_fingerprint": "fingerprint-original",
                "account_id": "acc-owner",
                "model": "gpt-6.1-sol",
                "state": "completed",
                "response_id": "resp_owner",
                "event_spool_complete": True,
                "created_at": now,
                "updated_at": now,
            },
        ]
        async with async_sessionmaker(engine)() as session:
            await session.execute(insert(HttpBridgeOperationRecord), rows)
            await session.commit()
            repo = DurableBridgeRepository(session)
            assert await repo.completed_response_is_uninterrupted_session_head(
                session_id="durable-owner", account_id="acc-owner", response_id="resp_owner"
            )
            assert not await repo.completed_response_is_uninterrupted_session_head(
                session_id="durable-other", account_id="acc-owner", response_id="resp_owner"
            )
            assert not await repo.completed_response_is_uninterrupted_session_head(
                session_id="durable-owner", account_id="acc-other", response_id="resp_owner"
            )
            await session.execute(
                insert(HttpBridgeOperationRecord),
                [
                    {
                        "operation_id": "op_interrupted_or_newer",
                        "session_id": "durable-owner",
                        "request_fingerprint": "fingerprint-newer",
                        "account_id": "acc-owner",
                        "state": intervening_state,
                        "response_id": "resp_next" if intervening_state == "completed" else None,
                        "event_spool_complete": intervening_state == "completed",
                        # A prior operation may be retried/settled *after*
                        # the anchor, without changing its original created_at.
                        "created_at": now + timedelta(seconds=-1 if older_created else 1),
                        "updated_at": now + timedelta(seconds=1),
                    }
                ],
            )
            await session.commit()
            assert not await repo.completed_response_is_uninterrupted_session_head(
                session_id="durable-owner", account_id="acc-owner", response_id="resp_owner"
            )
    finally:
        await engine.dispose()
