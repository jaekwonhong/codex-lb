from __future__ import annotations

from typing import Protocol, TypeVar
from urllib.parse import quote, urlsplit, urlunsplit

import aiohttp
from pydantic import BaseModel, ValidationError

from app.modules.member_switch.repository import ControlConflict
from app.modules.member_switch.schemas import (
    CONTROL_PROTOCOL,
    Catalog,
    CompanionAdmission,
    EgoOAuthBrowserRequest,
    EgoOAuthBrowserResponse,
    EgoOAuthBrowserStatusRequest,
    EgoOAuthProfileRequest,
    EgoOAuthProfileResponse,
    FinalizeReceipt,
    MembershipObservation,
    Operation,
    ParticipantReceipt,
    ParticipantRequest,
    Preview,
    PreviewRequest,
    StartReceipt,
    StartRequest,
)


class CompanionPort(Protocol):
    async def admission(self) -> CompanionAdmission: ...
    async def catalog(self) -> Catalog: ...
    async def observe_membership(self, workspace_id: str) -> MembershipObservation: ...
    async def preview(self, request: PreviewRequest) -> Preview: ...
    async def start(self, request: StartRequest) -> StartReceipt: ...
    async def lookup(self, client_flow_id: str) -> StartReceipt | None: ...
    async def operation(self, operation_id: str) -> Operation: ...
    async def finalize(self, operation_id: str) -> FinalizeReceipt: ...
    async def participant(self, request: ParticipantRequest) -> ParticipantReceipt: ...
    async def participant_receipt(self, command_id: str) -> ParticipantReceipt | None: ...
    async def reconcile_participant_receipt(self, command_id: str) -> ParticipantReceipt | None: ...
    async def open_ego_oauth_browser(self, request: EgoOAuthBrowserRequest) -> EgoOAuthBrowserResponse: ...
    async def ego_oauth_browser_status(self, request: EgoOAuthBrowserStatusRequest) -> EgoOAuthBrowserResponse: ...
    async def ego_oauth_profile_status(self, request: EgoOAuthProfileRequest) -> EgoOAuthProfileResponse: ...


T = TypeVar("T", bound=BaseModel)


class CompanionClient:
    """Uses the existing trusted local endpoint, not a browser-supplied URL.

    Keep the Companion's Host/Origin boundary intact. The configured Docker host
    address is a transport address, not permission to relax that boundary.
    No retry is performed, including when only the response body is lost.
    """

    def __init__(self, account_pool_url: str | None) -> None:
        self._url: str | None = None
        if account_pool_url:
            parsed = urlsplit(account_pool_url)
            if (
                parsed.scheme != "http"
                or parsed.hostname not in {"127.0.0.1", "localhost", "host.docker.internal"}
                or parsed.port != 53418
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.path != "/member-switch/v1/account-pool"
            ):
                raise ControlConflict("companion_endpoint_invalid")
            self._url = urlunsplit((parsed.scheme, parsed.netloc, "/member-switch/v1", "", ""))

    async def _request(
        self,
        method: str,
        path: str,
        schema: type[T],
        request: BaseModel | None = None,
        *,
        missing_ok: bool = False,
        interactive: bool = False,
    ) -> T | None:
        if self._url is None:
            raise ControlConflict("companion_not_configured")
        try:
            timeout = aiohttp.ClientTimeout(total=190 if interactive else 30)
            async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
                async with session.request(
                    method,
                    self._url + path,
                    json=None if request is None else request.model_dump(mode="json", by_alias=True),
                    headers={
                        "Host": "127.0.0.1:53418",
                        "Origin": "http://127.0.0.1:2456",
                        "Accept": "application/json",
                        "X-Member-Switch-Protocol": CONTROL_PROTOCOL,
                    },
                    allow_redirects=False,
                ) as response:
                    if missing_ok and response.status == 404:
                        return None
                    # A 5xx body is not an authoritative rejection of a mutation.
                    if response.status >= 500 or 300 <= response.status < 400:
                        raise ControlConflict("companion_outcome_unknown")
                    if response.status in {401, 403, 404}:
                        raise ControlConflict("companion_request_unavailable")
                    return schema.model_validate(await response.json())
        except (aiohttp.ClientError, TimeoutError, ValidationError, ValueError) as exc:
            raise ControlConflict("companion_outcome_unknown") from exc

    async def _required(
        self, method: str, path: str, schema: type[T], request: BaseModel | None = None, *, interactive: bool = False
    ) -> T:
        result = await self._request(method, path, schema, request, interactive=interactive)
        if result is None:
            raise ControlConflict("companion_request_unavailable")
        return result

    async def catalog(self) -> Catalog:
        return await self._required("GET", "/catalog", Catalog)

    async def observe_membership(self, workspace_id: str) -> MembershipObservation:
        return await self._required(
            "POST",
            "/workspaces/" + quote(workspace_id, safe="") + "/observe",
            MembershipObservation,
            interactive=True,
        )

    async def admission(self) -> CompanionAdmission:
        return await self._required("GET", "/admission", CompanionAdmission)

    async def participant(self, request: ParticipantRequest) -> ParticipantReceipt:
        return await self._required("POST", "/participant-commands", ParticipantReceipt, request, interactive=True)

    async def participant_receipt(self, command_id: str) -> ParticipantReceipt | None:
        return await self._request(
            "GET", "/participant-commands/" + quote(command_id, safe=""), ParticipantReceipt, missing_ok=True
        )

    async def reconcile_participant_receipt(self, command_id: str) -> ParticipantReceipt | None:
        return await self._request(
            "POST",
            "/participant-commands/" + quote(command_id, safe="") + "/reconcile",
            ParticipantReceipt,
            missing_ok=True,
        )

    async def open_ego_oauth_browser(self, request: EgoOAuthBrowserRequest) -> EgoOAuthBrowserResponse:
        return await self._required(
            "POST",
            "/oauth-enrollment-browser/open",
            EgoOAuthBrowserResponse,
            request,
            interactive=True,
        )

    async def ego_oauth_browser_status(self, request: EgoOAuthBrowserStatusRequest) -> EgoOAuthBrowserResponse:
        return await self._required(
            "POST",
            "/oauth-enrollment-browser/status",
            EgoOAuthBrowserResponse,
            request,
        )

    async def ego_oauth_profile_status(self, request: EgoOAuthProfileRequest) -> EgoOAuthProfileResponse:
        return await self._required(
            "POST",
            "/oauth-enrollment-browser/profile-status",
            EgoOAuthProfileResponse,
            request,
        )

    async def preview(self, request: PreviewRequest) -> Preview:
        return await self._required("POST", "/previews", Preview, request)

    async def start(self, request: StartRequest) -> StartReceipt:
        return await self._required("POST", "/operations", StartReceipt, request)

    async def lookup(self, client_flow_id: str) -> StartReceipt | None:
        return await self._request(
            "GET", "/client-flows/" + quote(client_flow_id, safe=""), StartReceipt, missing_ok=True
        )

    async def operation(self, operation_id: str) -> Operation:
        return await self._required("GET", "/operations/" + quote(operation_id, safe=""), Operation)

    async def finalize(self, operation_id: str) -> FinalizeReceipt:
        return await self._required(
            "POST", "/operations/" + quote(operation_id, safe="") + "/finalize", FinalizeReceipt
        )
