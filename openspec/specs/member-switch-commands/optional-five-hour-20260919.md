# Optional 5H source qualification — 2026-09-19

The user clarified that 5H availability can vary by subscription and account, including absence. The implementation therefore reads each successful response instead of maintaining a subscription allowlist.

## Contract and example

A response with `primary_window.limit_window_seconds=604800` and `secondary_window=null` can supply valid Weekly retention plus explicit same-fetch 5H absence. The same applies to the opposite slot or an omitted sibling. Missing rate-limit data, an unclassified sibling, two ambiguous windows, failed fetches or identity mismatch never prove absence. A present but invalid 5H window still blocks final retention. Additional named rate limits do not substitute for the base 5H window.

The usage-owned immutable receipt carries a default-false absence flag. Only a successful actual response can set it; identity rejection, failed fetches and the legacy second-fetch confirmation path clear it. This flag plus the optional classified window yields observed / not_provided / unknown without a stored zero value.

New final snapshot provenance uses schema version 2 and binds availability to fetch, exact account/member identity, requested workspace and observation time. A legitimate Weekly-only epoch stores one Weekly row with absence provenance; a present 5H stores the existing two-row shape. Retention/recovery validate the expected row set and versioned evidence. Legacy complete pairs remain readable; incomplete legacy rows remain unknown and cannot recover an epoch. No DB schema migration is needed.

The operator API adds `not_provided` for current 5H and `fiveHourState` for history. The UI renders 미제공 separately from 미확인. Projection only applies to the outgoing identity whose epoch was validated, never to a newly joined member. Existing Weekly freshness, reset-first resolution, quota and effect boundaries remain in force.

## Verification

- 231 core Usage/foundation/quota/controller/scheduler/reset and operator API tests passed, including new Weekly-only recovery and no-replay cases.
- 135 runtime, host attestation and release-tool regression tests passed.
- 5 existing immutable snapshot repository tests passed.
- 22 operator UI tests passed; frontend typecheck, scoped ESLint, production build, backend scoped Ruff and application/test type checks passed.
- Local browser fixtures verified before/after/unknown display; screenshots and fixture sources are in the packet below.
- Strict OpenSpec change/umbrella/main-spec validation accompanies archive.

Packet: `/Users/nowtech/Documents/codex-lb-server/artifacts/rotation-optional-five-hour-20260919/`.

## Deployment and remaining work

This is source qualification using temporary SQLite, mocked upstream/Companion effects and local frontend fixtures. It is not a PostgreSQL deployment qualification or an independent review. No production reset, member removal, invitation, live canary, enabled intent, plan publication, container restart or deployment was performed. The previously deployed matched-OFF image has not acquired this source change. Prior sealed evidence packets remain historical and unchanged.

Next eligible work is independent review of this delta and a new OFF candidate/artifact qualification, subject to the repository release policy; live canary remains excluded. Do not reuse the old diagnostic failure or this source qualification as activation authority.
