## ADDED Requirements

### Requirement: Explicit membership-list refresh uses the exact owner Ego Lite profile
The managed catalog refresh SHALL resolve each workspace owner email to one non-archived managed account, derive `CodexLB-<stable account id>` as the browser profile authority, and inspect that workspace through a deterministic owner Ego Lite Task Space. It SHALL verify the current ChatGPT session email equals the workspace owner before reading members or invitations. It MUST NOT launch, attach to, reload, or fall back to a legacy owner CDP browser for this observation.

#### Scenario: Logged-in owner refreshes membership
- **WHEN** catalog refresh observes a workspace whose owner managed Ego Lite profile is logged in as the exact owner email
- **THEN** the system creates or reuses only that owner's deterministic Task Space and reads the workspace member/invite lists from it
- **AND** no owner CDP browser is opened or contacted for the observation

#### Scenario: Owner profile requires login or has the wrong identity
- **WHEN** the exact owner Ego Lite profile is missing, logged out, or logged in as another email
- **THEN** membership observation fails closed with an explicit Ego Lite owner status
- **AND** the system does not substitute another profile, system browser, or owner CDP browser

### Requirement: Owner Ego observation capability is negotiated before observation-dependent work
The backend SHALL require the Companion capability `ego_lite_owner_membership_observation_v1` before beginning explicit live catalog refresh, admitting a new managed member-switch run, or revalidating current membership for OAuth-only enrollment so a backend/Companion version mismatch cannot silently restore the legacy observation transport.

#### Scenario: Old Companion lacks owner Ego observation capability
- **WHEN** the backend receives a catalog without `ego_lite_owner_membership_observation_v1`
- **THEN** it rejects live catalog refresh before requesting any workspace observation
- **AND** it rejects new managed run creation before any run write or membership effect

### Requirement: Membership mutation transport remains out of scope
This change SHALL NOT alter the existing transport used for delete, invitation creation, or invitation cancellation.

#### Scenario: A later member-switch mutation executes
- **WHEN** the workflow performs delete, invite, or invite-cancel after observation
- **THEN** the existing mutation implementation remains responsible for that operation

#### Scenario: OAuth-only current-member validation sees an old Companion
- **WHEN** OAuth-only registration would revalidate current membership but the Companion lacks owner Ego observation capability
- **THEN** the backend rejects the validation before requesting workspace membership
- **AND** it does not fall back to an owner CDP observation
