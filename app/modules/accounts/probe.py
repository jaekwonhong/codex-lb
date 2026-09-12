from __future__ import annotations

import logging
from typing import Protocol

from app.core.audit.service import AuditService
from app.modules.accounts.schemas import AccountProbeResponse
from app.modules.accounts.service import AccountsService

logger = logging.getLogger(__name__)


class AccountProbeSettlementPort(Protocol):
    async def record_account_probe_result(self, *, account_id: str, http_status: int) -> None: ...


async def run_account_force_probe(
    *,
    service: AccountsService,
    settlement: AccountProbeSettlementPort,
    account_id: str,
    model: str | None = None,
    actor_ip: str | None = None,
    trigger: str = "dashboard_manual",
) -> AccountProbeResponse | None:
    """Run the canonical Force Probe and its advisory settlement/audit side effects."""
    result = await service.probe_account(account_id, model=model)
    if result is None:
        return None

    probe_succeeded = 200 <= result.probe_status_code < 300
    if not probe_succeeded or result.usage_refresh_ready_for_probe_settlement():
        try:
            await settlement.record_account_probe_result(
                account_id=result.account_id,
                http_status=result.probe_status_code,
            )
        except Exception:
            logger.exception(
                "Force Probe advisory settlement failed account_id=%s probe_status_code=%s trigger=%s",
                result.account_id,
                result.probe_status_code,
                trigger,
            )
    else:
        logger.warning(
            "Force Probe success skipped advisory settlement before successful usage refresh fetch "
            "account_id=%s probe_status_code=%s trigger=%s",
            result.account_id,
            result.probe_status_code,
            trigger,
        )

    logger.info(
        "Force Probe completed account_id=%s trigger=%s probe_status_code=%s "
        "primary_used_percent_after=%s secondary_used_percent_after=%s account_status_after=%s",
        result.account_id,
        trigger,
        result.probe_status_code,
        result.primary_used_percent_after,
        result.secondary_used_percent_after,
        result.account_status_after,
    )

    AuditService.log_async(
        "account_probed",
        actor_ip=actor_ip,
        details={
            "account_id": result.account_id,
            "probe_status_code": result.probe_status_code,
            "model": model,
            "trigger": trigger,
        },
    )
    return result
