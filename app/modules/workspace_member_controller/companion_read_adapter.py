from __future__ import annotations

from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from pydantic import ValidationError

from app.modules.workspace_member_controller.domain import Catalog, MembershipObservation
from app.modules.workspace_member_controller.ports import WorkspaceReadPort

_CONTROL_PROTOCOL = "managed_member_switch_v1"


class CompanionReadError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CompanionHttpReadAdapter(WorkspaceReadPort):
    """Read-only Companion adapter with the qualified local Host/Origin boundary."""

    def __init__(
        self,
        *,
        base_url: str,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30.0,
        observation_timeout_seconds: float = 190.0,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "host.docker.internal"}
            or parsed.port != 53418
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path.rstrip("/") != "/member-switch/v1"
        ):
            raise ValueError("companion_endpoint_invalid")
        self._base_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
        self._client = client
        self._timeout_seconds = timeout_seconds
        self._observation_timeout_seconds = observation_timeout_seconds

    async def catalog(self) -> Catalog:
        return await self._request("GET", "/catalog", Catalog)

    async def observe_membership(self, workspace_id: str) -> MembershipObservation:
        return await self._request(
            "POST",
            "/workspaces/" + quote(workspace_id, safe="") + "/observe",
            MembershipObservation,
            timeout_seconds=self._observation_timeout_seconds,
        )

    async def _request(self, method: str, path: str, schema, *, timeout_seconds: float | None = None):
        client = self._client or httpx.AsyncClient(trust_env=False)
        owns_client = self._client is None
        try:
            try:
                response = await client.request(
                    method,
                    self._base_url + path,
                    headers={
                        "Host": "127.0.0.1:53418",
                        "Origin": "http://127.0.0.1:2456",
                        "Accept": "application/json",
                        "X-Member-Switch-Protocol": _CONTROL_PROTOCOL,
                    },
                    timeout=self._timeout_seconds if timeout_seconds is None else timeout_seconds,
                    follow_redirects=False,
                )
            except httpx.HTTPError as exc:
                raise CompanionReadError("companion_read_unavailable") from exc
        finally:
            if owns_client:
                await client.aclose()
        if response.status_code != 200:
            raise CompanionReadError("companion_read_unavailable")
        try:
            return schema.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise CompanionReadError("companion_read_invalid") from exc
