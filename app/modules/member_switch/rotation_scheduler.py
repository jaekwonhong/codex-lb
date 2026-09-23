"""One explicitly planned Q3 evaluation. No plan means no DB/network work."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.core.config.settings import get_settings
from app.core.scheduling.leader_election_handle import get_leader_election
from app.modules.member_switch.rotation_plan import CanaryPlan, read_canary_plan

logger = logging.getLogger(__name__)


async def _leader(body: Callable[[], Awaitable[None]]) -> None:
    await get_leader_election().run_if_leader(body)


@dataclass
class RotationScheduler:
    directory: Path
    execute: Callable[[CanaryPlan], Awaitable[None]]
    leader: Callable[[Callable[[], Awaitable[None]]], Awaitable[None]] = _leader
    interval_seconds: float = 30
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    _task: asyncio.Task[None] | None = field(default=None, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def tick(self) -> None:
        # Reading the local plan is the sole work while OFF. Even leader election
        # would use the database, so do not acquire it before checking the plan.
        initial = read_canary_plan(self.directory)
        if initial is None or self.clock() >= initial.expires_at:
            return

        async def run() -> None:
            async with self._lock:
                plan = read_canary_plan(self.directory)
                if plan is not None and self.clock() < plan.expires_at:
                    await self.execute(plan)

        await self.leader(run)

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="member-rotation-scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task
            finally:
                self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                logger.exception("Member rotation scheduler tick blocked")
            await asyncio.sleep(self.interval_seconds)


def build_member_rotation_scheduler() -> RotationScheduler:
    from app.modules.member_switch.rotation_worker import RotationWorker

    directory = get_settings().data_dir / "member-rotation-runtime"
    return RotationScheduler(directory, RotationWorker(directory).run)
