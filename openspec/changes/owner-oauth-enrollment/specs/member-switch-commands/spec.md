## ADDED Requirements

### Requirement: Workspace owner is an OAuth-only target
Each workspace MAY expose an exact `ownerAuth` descriptor containing a synthetic OAuth target ID, owner email, owner user ID, and current auth status. The owner SHALL NOT be added to the member-switch candidate list and SHALL NOT change the existing member catalog fingerprint.

#### Scenario: Owner OAuth descriptor is available
- **WHEN** Companion has exactly one ready `OwnerAccountId` for the workspace with an exact user ID
- **THEN** the workspace exposes `ownerAuth` using `owner:<workspaceId>` while `members` remains unchanged

### Requirement: Owner identity uses authoritative existing account-pool/profile state
Owner OAuth enrollment SHALL resolve the exact workspace group `OwnerAccountId`, email, user ID, workspace account ID, and existing managed Ego Lite profile. It SHALL NOT infer a user ID, reuse another profile, create a new profile, or copy browser state.

#### Scenario: Owner browser automation starts
- **WHEN** owner one-click OAuth reaches the browser stage
- **THEN** Companion opens the existing `CodexLB-account-*` profile belonging to that workspace owner and applies the same exact account/workspace/device-code checks used for member OAuth

### Requirement: Owner enrollment reuses the one-click OAuth orchestration
An owner whose auth state is `absent` or `inactive` SHALL use the same durable automatic OAuth enrollment, server-owned post-registration Force Probe, progress reporting, and recovery semantics as a current member. No membership mutation SHALL be requested.

#### Scenario: Owner completes one-click OAuth
- **WHEN** the operator presses the owner's `OAuth 등록` button and authentication completes normally
- **THEN** the enrollment reaches terminal success without member removal/invitation/replacement, the exact owner auth account is persisted, and the server-owned Force Probe runs once

### Requirement: Owner authority remains separate from membership authority
Member reconciliation, candidate registration, preview, start, removal, invitation, and member catalog fingerprint calculations SHALL continue to use member entries only. Owner entries SHALL be visible only to OAuth identity validation and auth observation.

#### Scenario: Owner target is inspected as a member candidate
- **WHEN** member-switch candidate lookup is performed
- **THEN** `owner:<workspaceId>` is not returned and cannot be previewed or selected for membership replacement

### Requirement: Mixed-version owner OAuth fails closed
Owner OAuth enrollment SHALL require Companion capability `ego_lite_owner_oauth_enrollment_v1`. A Companion that does not advertise that capability SHALL continue to support existing member OAuth but SHALL reject owner OAuth before browser/OAuth effects.

#### Scenario: Old Companion receives owner enrollment
- **WHEN** the server receives an owner OAuth request while the capability is absent
- **THEN** it returns `companion_protocol_upgrade_required` and performs no OAuth/browser effect

### Requirement: Owner OAuth import accepts exact OwnerAccountId authority
When the OAuth result is imported, an exact ready account referenced as the workspace group's `OwnerAccountId` SHALL be accepted as workspace identity even though owners are intentionally excluded from member assignments.

#### Scenario: Owner has no member assignment
- **WHEN** the imported account exactly matches the workspace `OwnerAccountId`, email, and user ID but is not present in `Assignments`
- **THEN** import identity resolution succeeds for that owner without changing member assignments
