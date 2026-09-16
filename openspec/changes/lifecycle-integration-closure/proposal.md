# Lifecycle integration closure

Integrate the reviewed lifecycle repairs while rebasing onto the unmodified beta.9
upstream migration graph. Preserve the original review candidate as historical
evidence rather than carrying its local Alembic branch forward.

The application migration runner must leave the two retained member-control tables
outside Alembic ownership and execute all upstream revisions normally. Release
qualification must verify that both local extension tables and their retained data
survive the upstream migration before member-switch is enabled. It must not create,
stamp, merge or remap a local member-control revision. No production migration is
part of this integration.

Requalify source, frontend and Companion and investigate the prior broad-suite
fixture lock without adding retries or suppressing failed assertions.
