## ADDED Requirements

### Requirement: Managed auth and run identity share one verified catalog
Managed create, start and auth preparation SHALL use a request-local snapshot of
the trusted configured Companion catalog. The snapshot's canonical fingerprint
SHALL match its advertised fingerprint and the stored run identity. Legacy packaged
or overlay catalogs SHALL NOT override that managed authority. Legacy catalog files
SHALL remain unchanged. Stored-state GETs SHALL NOT acquire a remote catalog or
perform any participant action.

#### Scenario: Companion candidates differ from a historical auth catalog
- **WHEN** a managed request selects an identity from the current valid Companion catalog
- **THEN** preview and auth preparation use that same catalog rather than historical preset IDs
- **AND** no legacy catalog file is rewritten

#### Scenario: The catalog changes before auth preparation
- **WHEN** its fingerprint no longer matches the stored run
- **THEN** auth preparation is rejected before claiming the command, quarantining auth or starting OAuth

#### Scenario: A catalog advertises a fingerprint inconsistent with its entries
- **WHEN** the catalog is bound for managed execution
- **THEN** the request fails before any run write or participant mutation

### Requirement: Verified workspace choice controls remain executable
The recipient page action SHALL support the label, native radio and ARIA radio
controls that its observation producer can select. Origin, document epoch, visible
bounds and enabled state SHALL still be checked at execution. A label bound to a
disabled or missing input SHALL be rejected. No native-coordinate fallback is added.

#### Scenario: The observer selected a visible enabled radio or its label
- **WHEN** that control remains valid on the same trusted document
- **THEN** the page-side action clicks it once

#### Scenario: The selected control or document is no longer valid
- **WHEN** the epoch, origin, enabled state or current element does not match
- **THEN** it returns false without clicking any alternate control
