# Lifecycle integration closure

Integrate the reviewed lifecycle repairs without changing an already-merged
migration. Preserve the original review candidate as historical evidence.

The application migration runner must handle an already-materialized member-control
schema at its exact revision boundary. It must execute all predecessor migrations,
validate the existing tables and retained data, create only missing counterparts,
and acknowledge only that exact revision inside the same transaction. Empty
databases continue through the original migration. No production migration is part
of this integration.

Requalify source, frontend and Companion and investigate the prior broad-suite
fixture lock without adding retries or suppressing failed assertions.
