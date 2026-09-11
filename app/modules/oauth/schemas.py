from __future__ import annotations

from pydantic import model_validator

from app.modules.shared.schemas import DashboardModel


class OauthStartRequest(DashboardModel):
    force_method: str | None = None
    # When set, this OAuth flow is a TARGETED reauthentication of an existing
    # local account row. The returned login's seat identity is verified against
    # this row before any tokens are written, so a wrong browser identity cannot
    # overwrite a different seat that shares the same Team/Business workspace.
    account_id: str | None = None
    expected_email: str | None = None
    expected_chatgpt_user_id: str | None = None
    expected_chatgpt_account_id: str | None = None

    @model_validator(mode="after")
    def validate_expected_identity(self) -> "OauthStartRequest":
        expected = (
            self.expected_email,
            self.expected_chatgpt_user_id,
            self.expected_chatgpt_account_id,
        )
        if any(value is not None for value in expected) and not all(value for value in expected):
            raise ValueError("Expected OAuth identity requires email, user ID, and account ID")
        if any(expected) and (self.force_method or "").casefold() != "device":
            raise ValueError("Expected OAuth identity is supported only for device OAuth")
        return self


class OauthStartResponse(DashboardModel):
    flow_id: str | None = None
    method: str
    authorization_url: str | None = None
    callback_url: str | None = None
    verification_url: str | None = None
    user_code: str | None = None
    device_auth_id: str | None = None
    interval_seconds: int | None = None
    expires_in_seconds: int | None = None


class OauthStatusResponse(DashboardModel):
    status: str
    error_message: str | None = None


class OauthCompleteRequest(DashboardModel):
    flow_id: str | None = None
    device_auth_id: str | None = None
    user_code: str | None = None


class OauthCompleteResponse(DashboardModel):
    status: str


class ManualCallbackRequest(DashboardModel):
    callback_url: str
    flow_id: str | None = None


class ManualCallbackResponse(DashboardModel):
    status: str
    error_message: str | None = None
