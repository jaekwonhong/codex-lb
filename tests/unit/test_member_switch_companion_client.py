from __future__ import annotations

import pytest

from app.modules.member_switch.companion import CompanionClient
from app.modules.member_switch.repository import ControlConflict
from app.modules.member_switch.schemas import StartRequest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "url",
    [
        "https://remote.invalid:53418/member-switch/v1/account-pool",
        "http://127.0.0.1:2456/member-switch/v1/account-pool",
        "http://127.0.0.1:53418/member-switch/v1/account-pool?target=external",
        "http://user:password@127.0.0.1:53418/member-switch/v1/account-pool",
    ],
)
def test_only_configured_local_companion_endpoint_is_accepted(url):
    with pytest.raises(ControlConflict, match="companion_endpoint_invalid"):
        CompanionClient(url)


class FakeResponse:
    def __init__(self, status, payload, error=None):
        self.status, self.payload, self.error = status, payload, error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self):
        if self.error:
            raise self.error
        return self.payload


def intercept(monkeypatch, response):
    calls = []

    class Session:
        def __init__(self, **options):
            calls.append(("session", options))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def request(self, method, url, **options):
            calls.append((method, url, options))
            return response

    monkeypatch.setattr("app.modules.member_switch.companion.aiohttp.ClientSession", Session)
    return calls


@pytest.mark.parametrize(
    "status,payload,error",
    [
        (503, {"accepted": False, "code": "not_started", "operationId": None}, None),
        (302, None, None),
        (200, {"unexpected": True}, None),
        (200, None, TimeoutError("response body stalled")),
    ],
)
async def test_uncertain_responses_never_trigger_retry(monkeypatch, status, payload, error):
    calls = intercept(monkeypatch, FakeResponse(status, payload, error))
    client = CompanionClient("http://host.docker.internal:53418/member-switch/v1/account-pool")
    with pytest.raises(ControlConflict, match="outcome_unknown"):
        await client.start(StartRequest(preview_token="synthetic", client_flow_id="flow-id"))
    requests = [call for call in calls if call[0] == "POST"]
    assert len(requests) == 1
    options = requests[0][2]
    assert options["allow_redirects"] is False
    assert options["headers"]["Host"] == "127.0.0.1:53418"
    assert options["headers"]["Origin"] == "http://127.0.0.1:2456"
    assert calls[0][1]["trust_env"] is False
    assert calls[0][1]["timeout"].total == 30


async def test_missing_client_receipt_is_observation_not_start_permission(monkeypatch):
    calls = intercept(monkeypatch, FakeResponse(404, None))
    client = CompanionClient("http://127.0.0.1:53418/member-switch/v1/account-pool")
    assert await client.lookup("test-id") is None
    assert [call[0] for call in calls] == ["session", "GET"]


async def test_membership_observation_uses_managed_post_and_interactive_timeout(monkeypatch):
    calls = intercept(
        monkeypatch,
        FakeResponse(
            200,
            {
                "schemaVersion": 1,
                "available": True,
                "code": "ok",
                "workspaceId": "workspace/one",
                "workspaceAccountId": "account-1",
                "catalogFingerprint": "a" * 64,
                "observedAt": "2026-09-07T00:00:00Z",
                "complete": True,
                "ownerVerified": True,
                "identityAmbiguous": False,
                "partialIdentity": False,
                "duplicateIdentity": False,
                "unknownMember": False,
                "members": [],
            },
        ),
    )
    client = CompanionClient("http://127.0.0.1:53418/member-switch/v1/account-pool")

    result = await client.observe_membership("workspace/one")

    assert result.available is True
    request = next(call for call in calls if call[0] == "POST")
    assert request[1].endswith("/workspaces/workspace%2Fone/observe")
    assert request[2]["headers"]["X-Member-Switch-Protocol"] == "managed_member_switch_v1"
    assert calls[0][1]["timeout"].total == 190


async def test_close_reconciliation_is_explicit_protocol_post_and_not_a_close_retry(monkeypatch):
    calls = intercept(monkeypatch, FakeResponse(404, None))
    client = CompanionClient("http://127.0.0.1:53418/member-switch/v1/account-pool")
    assert await client.reconcile_participant_receipt("command/one") is None
    requests = [call for call in calls if call[0] != "session"]
    assert len(requests) == 1
    method, url, options = requests[0]
    assert method == "POST" and url.endswith("/participant-commands/command%2Fone/reconcile")
    assert options["headers"]["X-Member-Switch-Protocol"] == "managed_member_switch_v1"
    assert options["json"] is None
    assert options["allow_redirects"] is False
