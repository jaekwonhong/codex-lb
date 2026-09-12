from __future__ import annotations

import logging

from app.core.auth.refresh import RefreshError
from app.modules.accounts.probe import AccountProbeSettlementPort, run_account_force_probe
from app.modules.accounts.service import AccountNotProbableError, AccountsService
from app.modules.member_switch.schemas import AuthEnrollmentPostProbe

logger = logging.getLogger(__name__)


class MemberAuthPostProbeService:
    """Adapt the canonical account Force Probe to durable OAuth diagnostics."""

    def __init__(
        self,
        accounts: AccountsService,
        settlement: AccountProbeSettlementPort,
        *,
        actor_ip: str | None = None,
    ) -> None:
        self._accounts = accounts
        self._settlement = settlement
        self._actor_ip = actor_ip

    async def probe(self, account_id: str) -> AuthEnrollmentPostProbe:
        try:
            result = await run_account_force_probe(
                service=self._accounts,
                settlement=self._settlement,
                account_id=account_id,
                actor_ip=self._actor_ip,
                trigger="member_oauth_post_registration",
            )
        except AccountNotProbableError:
            return AuthEnrollmentPostProbe(state="failed", account_id=account_id, error_code="account_not_probable")
        except RefreshError:
            return AuthEnrollmentPostProbe(
                state="failed",
                account_id=account_id,
                error_code="account_probe_refresh_failed",
            )
        except Exception:
            logger.exception("Post-registration Force Probe failed account_id=%s", account_id)
            return AuthEnrollmentPostProbe(state="failed", account_id=account_id, error_code="account_probe_failed")

        if result is None:
            return AuthEnrollmentPostProbe(state="failed", account_id=account_id, error_code="account_not_found")
        return AuthEnrollmentPostProbe(
            state="completed",
            account_id=result.account_id,
            probe_status_code=result.probe_status_code,
            primary_used_percent_after=result.primary_used_percent_after,
            secondary_used_percent_after=result.secondary_used_percent_after,
            account_status_after=result.account_status_after,
        )
