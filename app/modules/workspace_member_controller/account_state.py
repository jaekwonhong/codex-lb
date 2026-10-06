from __future__ import annotations

from typing import Literal, Protocol

from pydantic import ConfigDict, Field, model_validator

from app.modules.workspace_member_controller.domain import ControllerModel


class OpenCodexQuotaWindow(ControllerModel):
    name: str = Field(min_length=1)
    used_percent: float
    reset_at: int | None = None
    observed_at: int | None = None


class OpenCodexCooldown(ControllerModel):
    scope: Literal["account", "shared", "reserve"]
    until: int
    source: str | None = None


class OpenCodexResetCreditState(ControllerModel):
    available_count: int = Field(ge=0)


class AccountDecisionEvidence(ControllerModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    provider: Literal["openai"] = "openai"
    account_id: str = Field(min_length=1)
    credential_generation: int | None = Field(default=None, ge=0)
    main_identity_generation: int | None = Field(default=None, ge=0)
    state_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    observed_at: int = Field(ge=0)
    quota_observed_at: int | None = Field(default=None, ge=0)
    selection_state: Literal["selectable", "excluded", "unknown"]
    quota_state: Literal["available", "exhausted", "unknown"]
    needs_reauth: bool
    paused: bool
    quota_windows: list[OpenCodexQuotaWindow] = Field(default_factory=list)
    reset_credit_available_count: int | None = Field(default=None, ge=0)


class OpenCodexAccountState(ControllerModel):
    schema_version: Literal[1]
    provider: Literal["openai"]
    account_id: str = Field(min_length=1)
    is_main: bool
    selector: str | None = None
    credential_generation: int | None = Field(default=None, ge=0)
    main_identity_generation: int | None = Field(default=None, ge=0)
    observed_at: int = Field(ge=0)
    has_credential: bool
    needs_reauth: bool
    paused: bool
    health_status: str = Field(min_length=1)
    selection_state: Literal["selectable", "excluded", "unknown"]
    exclusion_reasons: list[str] = Field(default_factory=list)
    quota_state: Literal["available", "exhausted", "unknown"]
    quota_observed_at: int | None = Field(default=None, ge=0)
    quota_windows: list[OpenCodexQuotaWindow] = Field(default_factory=list)
    reset_credit_state: OpenCodexResetCreditState | None = None
    cooldowns: list[OpenCodexCooldown] = Field(default_factory=list)
    state_revision: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_generation_namespace(self) -> OpenCodexAccountState:
        if self.is_main:
            if self.account_id != "__main__" or self.main_identity_generation is None:
                raise ValueError("main_account_generation_missing")
            if self.credential_generation is not None:
                raise ValueError("main_account_must_not_expose_pool_generation")
        elif self.account_id == "__main__":
            raise ValueError("pool_account_cannot_use_main_identity")
        return self

    def is_fresh(self, *, now_ms: int, max_age_ms: int) -> bool:
        age = now_ms - self.observed_at
        return max_age_ms >= 0 and 0 <= age <= max_age_ms

    def quota_is_fresh(self, *, now_ms: int, max_age_ms: int) -> bool:
        if self.quota_state == "unknown" or self.quota_observed_at is None:
            return False
        age = now_ms - self.quota_observed_at
        return max_age_ms >= 0 and 0 <= age <= max_age_ms


class OpenCodexAccountStatePort(Protocol):
    async def get(self, account_id: str) -> OpenCodexAccountState: ...


class OpenCodexAccountStateError(RuntimeError):
    def __init__(self, code: str, *, status_code: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class OpenCodexAccountNotFound(OpenCodexAccountStateError):
    pass
