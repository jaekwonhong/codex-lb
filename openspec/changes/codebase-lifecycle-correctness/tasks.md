## 1. Reproduce
- [x] Exercise OAuth-only lifecycle through real request-scoped services and durable child storage.
- [x] Exercise background token rotation with a known workspace routing policy.
- [x] Exercise late OAuth start/status/completion responses and overlapping polls.

## 2. Repair
- [x] Fix exact-child enrollment admission without weakening unrelated blockers.
- [x] Forward the missing background repository argument.
- [x] Fence ordinary OAuth UI lifecycle consumers.
- [x] Prevent failed Companion account-pool saves from leaking tentative identities or settings.
- [x] Preserve retained member-control extension tables outside upstream Alembic and fail release admission on missing or malformed definitions.
- [x] Synchronize generated settings documentation and the justified existing local field budget.

## 3. Qualify
- [x] Run impacted persistence/auth suites and full backend static checks.
- [x] Run frontend suite, production build, lint and isolated browser checks.
- [x] Review Companion and operational entrypoints without live effects.
- [x] Record evidence, remaining boundaries and unchanged production identities.

Historical pre-integration backend run: 8,855 passed, 105 skipped and one test-fixture SQLite lock error;
the affected 25-test module passes in isolation. Keep the original run classified
with that error; qualification is WARN, not unconditional full-suite PASS.

Integrated frozen-input run: 8,864 passed, 105 skipped, no failures or errors.
The old lock was not reproduced; this is not a claim to have fixed its root cause.
The beta.9 integration keeps the upstream Alembic graph authoritative; retained
member-control tables and data are qualified separately, with no local revision
replayed, stamped or fabricated.
