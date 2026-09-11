## ADDED Requirements

### Requirement: Confirmed settings saves publish the returned settings snapshot
The settings UI SHALL publish the validated settings PUT response, including its
version, to the settings query cache before reporting mutation completion. A failed
follow-up read SHALL NOT discard this confirmed snapshot. Subsequent settings forms
SHALL use that version rather than the pre-save version. Existing refresh and
settings-conflict handling SHALL remain available; mutations SHALL NOT auto-retry.
If the cache already holds a higher server version, a delayed PUT response SHALL
NOT replace that newer confirmed snapshot.

#### Scenario: Save succeeds but the following read is unavailable
- **WHEN** a settings PUT returns a newer settings snapshot and its follow-up GET fails
- **THEN** the UI retains the returned saved values and version and shows the read failure
- **AND** a later save built from that displayed snapshot carries the saved version

#### Scenario: A delayed save response is older than a subsequent confirmed read
- **WHEN** the settings cache has a higher version than a completed PUT response
- **THEN** the UI retains the newer snapshot rather than reverting to the delayed response

### Requirement: Settings event handlers consume save rejections
The settings page SHALL handle rejections of its event-only save callback without
an unhandled promise rejection. It SHALL preserve the mutation error and existing
error presentation and SHALL NOT report a failed save as successful or repeat it.

#### Scenario: An operator toggles a setting and the server rejects it
- **WHEN** the save fails
- **THEN** the page shows the failure, leaves the confirmed value unchanged and re-enables controls
- **AND** no unhandled rejection or additional write is emitted

### Requirement: Proxy diagnostic results describe the latest attempt
Starting a new settings-page proxy endpoint test SHALL clear that endpoint's old
displayed result. A rejected test SHALL display failure instead of retaining an
earlier success. Completion SHALL release the local busy state without automatic retry.

#### Scenario: A successful endpoint test is followed by a rejected test
- **WHEN** the next test is started and fails
- **THEN** the previous successful result is hidden while waiting and replaced by failure
- **AND** the operator may explicitly test again without an unhandled rejection
