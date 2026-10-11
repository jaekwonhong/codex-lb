"""Proof-backed, same-owner fresh WebSocket reattachment.

This is an admission-time operation, never a retry of an in-flight response.
The recorder stores completed upstream responses, but a response ID does not
by itself prove that a newly opened WebSocket can resolve it. When a complete
durable transcript is available we can carry the context instead of guessing
that the old socket's anchor remains resolvable.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.core.openai.requests import ResponsesRequest
from app.core.utils.sse import parse_sse_data_json
from app.modules.proxy.replay_safety import (
    project_durable_transcript_for_account_neutral_fresh_replay,
)


def rebuild_verified_fresh_reattach(
    *,
    payload: ResponsesRequest,
    response_id: str,
    owner_account_id: str,
    durable_session_id: str,
    transcript: Sequence[object] | None,
) -> ResponsesRequest | None:
    """Reconstruct a prior context only with a completed, owner-bound chain.

    The durable repository has already bounded the chain by turns and bytes.
    The pure replay projector independently checks parent links, account-
    neutral item shapes, missing tool results, and its own item/byte budget.
    Keep this final origin check outside the projector: other callers may
    legitimately relocate an archived chain from a different session, whereas
    reattachment may *only* rebuild the exact session it is about to serve.
    """

    if (
        not response_id
        or not owner_account_id
        or not durable_session_id
        or payload.previous_response_id is not None
        or payload.conversation
        or not isinstance(payload.input, list)
        or not payload.input
        or not transcript
    ):
        return None
    last_operation = getattr(transcript[-1], "operation", None)
    if (
        getattr(last_operation, "response_id", None) != response_id
        or getattr(last_operation, "session_id", None) != durable_session_id
        or getattr(last_operation, "account_id", None) != owner_account_id
        # An incomplete response is not an authoritative last answer even
        # when the spool contains a syntactically valid terminal event.
        or any(
            getattr(getattr(turn, "operation", None), "state", None) != "completed"
            or getattr(getattr(turn, "operation", None), "session_id", None) != durable_session_id
            or getattr(getattr(turn, "operation", None), "account_id", None) != owner_account_id
            or not _has_matching_completed_response_event(turn)
            for turn in transcript
        )
    ):
        return None

    # No mutation of the client's body or its original affinity/owner state.
    # The temporary anchor is only the evidence used by the projector to
    # verify which durable chain this new turn continues.
    proposed = dict(payload.to_payload())
    proposed["previous_response_id"] = response_id
    projection = project_durable_transcript_for_account_neutral_fresh_replay(
        transcript,
        anchor_response_id=response_id,
        current_payload=proposed,
    )
    if projection is None:
        return None
    try:
        rebuilt = ResponsesRequest.model_validate(projection.payload)
    except ValueError:
        return None
    if (
        rebuilt.previous_response_id is not None
        or rebuilt.conversation
        or rebuilt.model != payload.model
        or not isinstance(rebuilt.input, list)
        or len(rebuilt.input) < len(payload.input)
    ):
        return None
    return rebuilt


def _has_matching_completed_response_event(turn: object) -> bool:
    """No partial or foreign event can impersonate the completed turn record.

    The general cross-account projector accepts response.incomplete as an
    answered terminal for some safe migrations. Fresh WebSocket reattachment
    needs a *completed* response with the **same** id as the durable operation:
    otherwise it could reconstruct output from a partial or superseded turn.
    """

    response_id = getattr(getattr(turn, "operation", None), "response_id", None)
    events = getattr(turn, "events", None)
    if not isinstance(response_id, str) or not response_id or not isinstance(events, (list, tuple)):
        return False
    completed_count = 0
    for event_text in events:
        if not isinstance(event_text, str):
            return False
        event = parse_sse_data_json(event_text)
        if not isinstance(event, dict):
            continue
        if event.get("type") == "response.incomplete":
            return False
        if event.get("type") != "response.completed":
            continue
        response = event.get("response")
        if not isinstance(response, dict) or response.get("id") != response_id:
            return False
        completed_count += 1
    return completed_count == 1
