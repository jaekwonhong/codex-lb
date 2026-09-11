## Implementation
- [x] Persist typed participant intent and completion before publication.
- [x] Wire command admission and read-only lookup; refuse legacy direct browser/session writes.
- [x] Separate session preparation and reconcile only exact completed receipts.
- [x] Verify reply loss, restart, conflicting identity, concurrent calls and storage failure using synthetic participants.
- [x] Revalidate, replay incremental patches, and preserve the parent candidate.
