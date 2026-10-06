from __future__ import annotations

from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from app.modules.workspace_member_controller.account_state import (
    OpenCodexAccountNotFound,
    OpenCodexAccountState,
    OpenCodexAccountStateError,
    OpenCodexAccountStatePort,
)


class OpenCodexHttpAccountStateAdapter(OpenCodexAccountStatePort):
    """Read exact non-secret account state from OpenCodex's management plane."""

    def __init__(
        self,
        *,
        base_url: str,
        admin_token: str,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("invalid_opencodex_management_base_url")
        token = admin_token.strip()
        if not token:
            raise ValueError("missing_opencodex_admin_token")
        self._base_url = base_url.rstrip("/")
        self._admin_token = token
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def get(self, account_id: str) -> OpenCodexAccountState:
        if not account_id or any(ch in account_id for ch in "\r\n"):
            raise OpenCodexAccountStateError("invalid_account_id")
        request_url = f"{self._base_url}/api/codex-auth/controller-account-state"
        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        try:
            try:
                response = await client.get(
                    request_url,
                    params={"accountId": account_id},
                    headers={
                        "Authorization": f"Bearer {self._admin_token}",
                        "Accept": "application/json",
                    },
                    timeout=self._timeout_seconds,
                )
            except httpx.HTTPError as exc:
                raise OpenCodexAccountStateError("opencodex_account_state_unavailable") from exc
        finally:
            if owns_client:
                await client.aclose()

        if response.status_code == 404:
            raise OpenCodexAccountNotFound("opencodex_account_not_found", status_code=404)
        if response.status_code in {401, 403}:
            raise OpenCodexAccountStateError("opencodex_account_state_unauthorized", status_code=response.status_code)
        if response.status_code != 200:
            raise OpenCodexAccountStateError("opencodex_account_state_unavailable", status_code=response.status_code)

        try:
            state = OpenCodexAccountState.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise OpenCodexAccountStateError("opencodex_account_state_invalid") from exc
        if state.account_id != account_id:
            raise OpenCodexAccountStateError("opencodex_account_identity_mismatch")
        return state
