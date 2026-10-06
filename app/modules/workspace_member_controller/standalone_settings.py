from __future__ import annotations

import ipaddress
import stat
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class StandaloneSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WMC_", extra="ignore")

    host: str = "127.0.0.1"
    port: int = Field(default=2461, ge=1, le=65535)
    database_url: SecretStr
    companion_base_url: str = "http://127.0.0.1:53418/member-switch/v1"
    opencodex_management_base_url: str = "http://127.0.0.1:10101"
    account_bindings_path: Path
    admin_token: SecretStr | None = None
    admin_token_file: Path | None = None
    opencodex_admin_token: SecretStr | None = None
    opencodex_admin_token_file: Path | None = None
    allow_non_loopback_bind: bool = False

    @model_validator(mode="after")
    def validate_security_boundary(self) -> StandaloneSettings:
        _require_one_secret(self.admin_token, self.admin_token_file, "admin_token")
        _require_one_secret(
            self.opencodex_admin_token,
            self.opencodex_admin_token_file,
            "opencodex_admin_token",
        )
        if not _is_loopback_host(self.host) and not self.allow_non_loopback_bind:
            raise ValueError("non_loopback_bind_requires_explicit_opt_in")
        if not self.account_bindings_path.is_absolute():
            raise ValueError("account_bindings_path_must_be_absolute")
        for path, name in (
            (self.admin_token_file, "admin_token_file"),
            (self.opencodex_admin_token_file, "opencodex_admin_token_file"),
        ):
            if path is not None and not path.is_absolute():
                raise ValueError(f"{name}_must_be_absolute")
        parsed = urlsplit(self.opencodex_management_base_url)
        if parsed.scheme == "http" and parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "host.docker.internal",
        }:
            raise ValueError("plaintext_remote_opencodex_management_forbidden")
        return self

    def resolved_admin_token(self) -> str:
        return _resolve_secret(self.admin_token, self.admin_token_file, "admin_token")

    def resolved_opencodex_admin_token(self) -> str:
        return _resolve_secret(
            self.opencodex_admin_token,
            self.opencodex_admin_token_file,
            "opencodex_admin_token",
        )

    def resolved_database_url(self) -> str:
        raw = self.database_url.get_secret_value().strip()
        if ":memory:" in raw:
            raise ValueError("controller_database_must_be_durable")
        if raw.startswith("sqlite:///") and not raw.startswith("sqlite+aiosqlite:///"):
            path = raw.removeprefix("sqlite:///")
            if not path.startswith("/"):
                raise ValueError("controller_sqlite_path_must_be_absolute")
            return "sqlite+aiosqlite:///" + path
        if raw.startswith("postgresql://"):
            return "postgresql+asyncpg://" + raw.removeprefix("postgresql://")
        if raw.startswith("sqlite+aiosqlite:///"):
            if not raw.removeprefix("sqlite+aiosqlite:///").startswith("/"):
                raise ValueError("controller_sqlite_path_must_be_absolute")
            return raw
        if raw.startswith("postgresql+asyncpg://"):
            return raw
        raise ValueError("unsupported_controller_database_url")


def _require_one_secret(value: SecretStr | None, path: Path | None, name: str) -> None:
    if (value is None) == (path is None):
        raise ValueError(f"{name}_requires_exactly_one_source")


def _resolve_secret(value: SecretStr | None, path: Path | None, name: str) -> str:
    if value is not None:
        secret = value.get_secret_value().strip()
    else:
        assert path is not None
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
            if mode & 0o077:
                raise ValueError(f"{name}_file_permissions_too_open")
            secret = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError(f"{name}_file_unavailable") from exc
    if len(secret) < 32:
        raise ValueError(f"{name}_too_short")
    if "\r" in secret or "\n" in secret:
        raise ValueError(f"{name}_invalid")
    return secret


def _is_loopback_host(host: str) -> bool:
    if host.strip().casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
