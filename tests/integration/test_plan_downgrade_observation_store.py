"""Database-backed behaviour of the plan-downgrade observation store (#1456).

The unit suite exercises the in-memory analogue of this store; everything here
drives the real ``PlanDowngradeObservationStore`` against the migrated schema,
so the conditional upsert (``INSERT .. ON CONFLICT DO UPDATE .. RETURNING``),
its datetime binds, the read-first clear gate, and the replacement-time discard
run on the engine under test. These tests are part of the PostgreSQL CI
allowlist (``POSTGRES_PYTEST_TARGETS``) because production runs PostgreSQL and
the raw SQL and its binds must be proven per driver, not only on SQLite.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import delete, event, select
from sqlalchemy.engine import Engine

from app.core.crypto import TokenEncryptor
from app.core.utils.time import utcnow
from app.db.models import Account, AccountPlanDowngradeObservation, AccountStatus, Base
from app.db.session import SessionLocal, engine
from app.modules.usage.plan_downgrade_observations import (
    PlanDowngradeObservationStore,
    discard_plan_downgrade_observations,
)

pytestmark = pytest.mark.integration

_TABLE = AccountPlanDowngradeObservation.__tablename__


def _make_account(account_id: str, email: str) -> Account:
    encryptor = TokenEncryptor()
    return Account(
        id=account_id,
        chatgpt_account_id=f"upstream_{account_id}",
        email=email,
        plan_type="plus",
        access_token_encrypted=encryptor.encrypt("access"),
        refresh_token_encrypted=encryptor.encrypt("refresh"),
        id_token_encrypted=encryptor.encrypt("id"),
        last_refresh=utcnow(),
        status=AccountStatus.ACTIVE,
        deactivation_reason=None,
    )


async def _seed_account(account_id: str, email: str) -> None:
    """Insert the accounts row the observation row's foreign key requires."""
    async with SessionLocal() as session:
        session.add(_make_account(account_id, email))
        await session.commit()


async def _refresh_token_ciphertext(account_id: str) -> bytes:
    async with SessionLocal() as session:
        account = await session.get(Account, account_id)
        assert account is not None
        return account.refresh_token_encrypted


async def _replace_refresh_token(account_id: str, plaintext: str) -> bytes:
    replacement = TokenEncryptor().encrypt(plaintext)
    async with SessionLocal() as session:
        account = await session.get(Account, account_id)
        assert account is not None
        account.refresh_token_encrypted = replacement
        await session.commit()
    return replacement


@contextmanager
def _capture_observation_statements() -> Iterator[list[str]]:
    """Record every statement touching the observations table.

    Listens at the ``Engine`` class level rather than on one engine instance:
    the store reads and writes through ``get_background_session()``, whose
    lazily created background engine is a *separate* engine object for file and
    PostgreSQL databases, so an instance-level listener on the main engine goes
    blind once an earlier test has initialized it.
    """
    statements: list[str] = []

    def _before_cursor_execute(
        _connection,
        _cursor,
        statement: str,
        _parameters,
        _context,
        _executemany: bool,
    ) -> None:
        if _TABLE in statement:
            statements.append(statement.lstrip().upper())

    event.listen(Engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield statements
    finally:
        event.remove(Engine, "before_cursor_execute", _before_cursor_execute)


@pytest.mark.asyncio
async def test_observe_inserts_increments_and_restarts_on_lineage_change(db_setup):
    """The conditional upsert must run correctly on the engine under test.

    Covers the raw SQL end to end: the first observation inserts, an agreeing
    lineage increments through the ``ON CONFLICT`` branch, a changed lineage
    restarts at one via the ``CASE``, and ``RETURNING`` reports the resulting
    count — with the naive-UTC datetime binds written and read back through the
    real driver.
    """
    await _seed_account("acc_store_upsert", "store-upsert@example.com")
    store = PlanDowngradeObservationStore()

    assert await store.observe("acc_store_upsert", credential_fingerprint="fp-a", observed_plan_type="free") == 1
    assert await store.observe("acc_store_upsert", credential_fingerprint="fp-a", observed_plan_type="free") == 2

    recorded = await store.get("acc_store_upsert")
    assert recorded is not None
    assert recorded.observations == 2
    assert recorded.credential_fingerprint == "fp-a"
    assert recorded.observed_plan_type == "free"

    async with SessionLocal() as session:
        row = await session.get(AccountPlanDowngradeObservation, "acc_store_upsert")
        assert row is not None
        assert row.first_observed_at <= row.last_observed_at
        assert row.first_observed_at.tzinfo is None, "the store writes naive UTC like the rest of the schema"

    # A changed lineage restarts the sequence inside the same statement.
    assert await store.observe("acc_store_upsert", credential_fingerprint="fp-b", observed_plan_type="free") == 1
    restarted = await store.get("acc_store_upsert")
    assert restarted is not None
    assert restarted.observations == 1
    assert restarted.credential_fingerprint == "fp-b"


@pytest.mark.asyncio
async def test_concurrent_observations_advance_the_count_through_the_database(db_setup):
    """Concurrent upserts for one account must each see a distinct count.

    Every task calls the real store, so each observation is its own session,
    connection, and transaction against the shared database. On PostgreSQL the
    statements genuinely race and the single-statement upsert's row-level
    serialization is what keeps the counts distinct; on SQLite the process-wide
    writer section serializes the writes and the same invariant must hold.
    """
    await _seed_account("acc_store_concurrent", "store-concurrent@example.com")
    store = PlanDowngradeObservationStore()
    expected_refresh_token_encrypted = await _refresh_token_ciphertext("acc_store_concurrent")
    concurrency = 5
    barrier = asyncio.Barrier(concurrency)

    async def observe_after_barrier() -> int:
        await barrier.wait()
        observations = await store.observe_if_current(
            "acc_store_concurrent",
            expected_refresh_token_encrypted=expected_refresh_token_encrypted,
            credential_fingerprint="fp-shared",
            observed_plan_type="free",
        )
        assert observations is not None
        return observations

    results = await asyncio.gather(*(observe_after_barrier() for _ in range(concurrency)))

    assert sorted(results) == [1, 2, 3, 4, 5], "a lost update would repeat a count"
    recorded = await store.get("acc_store_concurrent")
    assert recorded is not None
    assert recorded.observations == concurrency


@pytest.mark.asyncio
async def test_stale_free_after_credential_replacement_cannot_seed_new_generation(db_setup):
    """A late free response from the old credential must miss after replacement."""
    account_id = "acc_store_stale_free"
    await _seed_account(account_id, "store-stale-free@example.com")
    stale_refresh_token_encrypted = await _refresh_token_ciphertext(account_id)
    current_refresh_token_encrypted = await _replace_refresh_token(account_id, "refresh-replaced")
    store = PlanDowngradeObservationStore()

    assert (
        await store.observe_if_current(
            account_id,
            expected_refresh_token_encrypted=stale_refresh_token_encrypted,
            credential_fingerprint="fp-stable-seat",
            observed_plan_type="free",
        )
        is None
    )
    assert await store.get(account_id) is None

    assert (
        await store.observe_if_current(
            account_id,
            expected_refresh_token_encrypted=current_refresh_token_encrypted,
            credential_fingerprint="fp-stable-seat",
            observed_plan_type="free",
        )
        == 1
    )


@pytest.mark.asyncio
async def test_stale_paid_after_credential_replacement_cannot_clear_new_generation_evidence(db_setup):
    """A late paid response from the old credential must not erase fresh evidence."""
    account_id = "acc_store_stale_paid"
    await _seed_account(account_id, "store-stale-paid@example.com")
    stale_refresh_token_encrypted = await _refresh_token_ciphertext(account_id)
    current_refresh_token_encrypted = await _replace_refresh_token(account_id, "refresh-replaced")
    store = PlanDowngradeObservationStore()

    assert (
        await store.observe_if_current(
            account_id,
            expected_refresh_token_encrypted=current_refresh_token_encrypted,
            credential_fingerprint="fp-stable-seat",
            observed_plan_type="free",
        )
        == 1
    )

    assert not await store.clear_if_current(
        account_id,
        expected_refresh_token_encrypted=stale_refresh_token_encrypted,
    )
    recorded = await store.get(account_id)
    assert recorded is not None
    assert recorded.observations == 1

    assert await store.clear_if_current(
        account_id,
        expected_refresh_token_encrypted=current_refresh_token_encrypted,
    )
    assert await store.get(account_id) is None


@pytest.mark.asyncio
async def test_missing_evidence_revokes_an_older_confirming_clear(db_setup):
    """A newer paid observation that already cleared evidence cancels an old confirmer."""
    account_id = "acc_store_confirmation_revoked"
    await _seed_account(account_id, "store-confirmation-revoked@example.com")
    current_refresh_token_encrypted = await _refresh_token_ciphertext(account_id)
    store = PlanDowngradeObservationStore()

    assert (
        await store.observe_if_current(
            account_id,
            expected_refresh_token_encrypted=current_refresh_token_encrypted,
            credential_fingerprint="fp-stable-seat",
            observed_plan_type="free",
        )
        == 1
    )
    assert await store.clear_if_current(
        account_id,
        expected_refresh_token_encrypted=current_refresh_token_encrypted,
    )

    assert not await store.clear_if_current(
        account_id,
        expected_refresh_token_encrypted=current_refresh_token_encrypted,
    )


@pytest.mark.asyncio
async def test_guarded_clear_requires_an_actual_deleted_evidence_row(db_setup, monkeypatch):
    """A row cleared after the outer probe cannot make an older confirmer succeed."""
    account_id = "acc_store_clear_toctou"
    await _seed_account(account_id, "store-clear-toctou@example.com")
    current_refresh_token_encrypted = await _refresh_token_ciphertext(account_id)
    store = PlanDowngradeObservationStore()
    assert (
        await store.observe_if_current(
            account_id,
            expected_refresh_token_encrypted=current_refresh_token_encrypted,
            credential_fingerprint="fp-stable-seat",
            observed_plan_type="free",
        )
        == 1
    )

    original = PlanDowngradeObservationStore._credential_is_current

    async def clear_after_generation_lock(session, locked_account_id, expected):
        is_current = await original(session, locked_account_id, expected)
        await session.execute(
            delete(AccountPlanDowngradeObservation).where(
                AccountPlanDowngradeObservation.account_id == locked_account_id
            )
        )
        return is_current

    monkeypatch.setattr(
        PlanDowngradeObservationStore,
        "_credential_is_current",
        staticmethod(clear_after_generation_lock),
    )

    assert not await store.clear_if_current(
        account_id,
        expected_refresh_token_encrypted=current_refresh_token_encrypted,
    )


@pytest.mark.asyncio
async def test_clear_skips_the_write_path_when_no_evidence_exists(db_setup):
    """A paid refresh on a healthy account must stay read-only.

    Every workspace-less refresh that reports a paid plan clears pending
    evidence, and on a healthy account there is none — so the common case must
    be a primary-key read with no ``DELETE`` and no ``COMMIT`` behind the
    process-wide writer section. The write path is taken only when a row
    actually exists.
    """
    await _seed_account("acc_store_gate", "store-gate@example.com")
    store = PlanDowngradeObservationStore()

    with _capture_observation_statements() as statements:
        await store.clear("acc_store_gate")
    assert statements, "the gate reads before deciding"
    assert all(statement.startswith("SELECT") for statement in statements), (
        "clearing without pending evidence must not write"
    )

    assert await store.observe("acc_store_gate", credential_fingerprint="fp", observed_plan_type="free") == 1
    with _capture_observation_statements() as statements:
        await store.clear("acc_store_gate")
    assert any(statement.startswith("DELETE") for statement in statements), "pending evidence must still be deleted"
    assert await store.get("acc_store_gate") is None


@pytest.mark.asyncio
async def test_discard_runs_inside_the_callers_transaction(db_setup):
    """Replacement-time discard must be atomic with the credential replacement.

    The accounts repository calls ``discard_plan_downgrade_observations`` with
    its own session while applying fresh credential material, so the evidence
    reset commits or rolls back together with the replacement itself.
    """
    await _seed_account("acc_store_discard", "store-discard@example.com")
    store = PlanDowngradeObservationStore()
    assert await store.observe("acc_store_discard", credential_fingerprint="fp", observed_plan_type="free") == 1

    async with SessionLocal() as session:
        account = await session.get(Account, "acc_store_discard")
        assert account is not None
        account.alias = "replaced"
        await discard_plan_downgrade_observations(session, "acc_store_discard")
        await session.commit()

    assert await store.get("acc_store_discard") is None
    async with SessionLocal() as session:
        replaced = await session.get(Account, "acc_store_discard")
        assert replaced is not None and replaced.alias == "replaced"


@pytest.mark.asyncio
async def test_discard_tolerates_a_not_yet_migrated_database(db_setup):
    """A missing observations table must not fail the credential replacement.

    The table arrives with this change, so a replica can apply fresh credentials
    against a database whose migration has not run yet. The discard runs in a
    SAVEPOINT precisely so that failure degrades to a warning without poisoning
    the caller's transaction — on PostgreSQL a failed statement would otherwise
    abort the whole transaction and the import or reauthentication with it.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.tables[_TABLE].drop)

    await _seed_account("acc_store_unmigrated", "store-unmigrated@example.com")

    async with SessionLocal() as session:
        account = await session.get(Account, "acc_store_unmigrated")
        assert account is not None
        account.alias = "survives-missing-schema"
        await discard_plan_downgrade_observations(session, "acc_store_unmigrated")
        await session.commit()

    async with SessionLocal() as session:
        result = await session.execute(select(Account).where(Account.id == "acc_store_unmigrated"))
        stored = result.scalar_one()
        assert stored.alias == "survives-missing-schema", (
            "the replacement itself must commit even when the discard degrades"
        )
