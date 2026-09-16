## ADDED Requirements

### Requirement: Rotation exhaustion uses a freshly classified Weekly window

Usage-driven Business member rotation SHALL consume a Weekly observation only when the current workspace member maps exactly to the observed account, an upstream usage fetch for that account succeeded, and the response contains a window that current normalization rules classify as the actual Weekly window from its shape and window metadata. Rotation SHALL NOT infer Weekly semantics from the storage/presentation slot name alone. The observation SHALL preserve the source slot, raw used percentage, window duration, reset timestamp, observation timestamp, and fetch provenance used for the decision.

The exhaustion decision SHALL use the unrounded numeric usage value, not the rounded dashboard display. Missing, `null`, placeholder, unclassified, or failed-fetch data SHALL be `unknown`, not exhausted. A previously exhausted Weekly observation whose reset deadline has elapsed SHALL NOT authorize rotation; the system SHALL obtain a new successful Weekly observation first.

`fetch_succeeded` and `usage_written` SHALL remain independent facts. A successful fetch that writes no row because the value is unchanged MAY provide fresh evidence when the returned Weekly observation is attributable to that fetch. A failed fetch MUST NOT make previously stored Weekly data fresh merely because it remains visible.

When rotation captures the outgoing member's final retained Usage evidence, the usage-owned fetch receipt SHALL expose the classified 5H and Weekly windows from the same successful upstream response together with one immutable fetch provenance record. The retention path SHALL NOT reconstruct either final window from persisted Usage rows. If either required window is missing, unclassified, or not attributable to the exact current member and successful fetch, membership mutation SHALL remain blocked.

#### Scenario: Weekly-only quota arrives in the primary slot
- **GIVEN** the current member maps exactly to an account
- **AND** a successful usage fetch returns a primary-slot window whose current normalization rules identify it as Weekly
- **WHEN** rotation evaluates Weekly exhaustion
- **THEN** it evaluates that classified Weekly window rather than requiring a secondary-slot row
- **AND** it records the original slot and window metadata as provenance

#### Scenario: Five-hour refresh does not refresh stale Weekly evidence
- **GIVEN** a successful fetch or live update produces a fresh 5H observation
- **AND** the last Weekly observation is older, missing, or otherwise not attributable to current successful Weekly evidence
- **WHEN** rotation evaluates the member
- **THEN** Weekly state remains unknown/stale
- **AND** the fresh 5H value does not authorize a replacement

#### Scenario: Successful unchanged fetch remains distinct from fetch failure
- **GIVEN** the stored Weekly value is unchanged
- **WHEN** a forced account refresh successfully fetches the same Weekly value and therefore writes no new usage row
- **THEN** `fetch_succeeded=true` remains available as fresh-fetch evidence even though `usage_written=false`
- **BUT WHEN** the fetch fails and leaves the same old stored row visible
- **THEN** that old row does not become fresh evidence

#### Scenario: Elapsed exhausted window must be re-observed
- **GIVEN** the last classified Weekly observation was exhausted
- **AND** its `reset_at` is now in the past
- **WHEN** rotation evaluates eligibility
- **THEN** it does not reuse the old exhausted value
- **AND** replacement remains blocked until a new successful Weekly observation is classified

#### Scenario: Final 5H and Weekly retention uses one fetch receipt
- **GIVEN** the exact outgoing member maps to a current account
- **AND** one successful forced Usage fetch returns classifiable 5H and Weekly windows
- **WHEN** rotation prepares the immutable pre-removal Usage snapshot
- **THEN** both windows carry the same fetch provenance and their original source-slot/window metadata
- **AND** `usage_written=false` does not invalidate that same-fetch evidence
- **BUT WHEN** the response omits either required window or the fetch fails
- **THEN** persisted rows from an earlier fetch are not substituted
- **AND** the removal prerequisite remains unsatisfied
