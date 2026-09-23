## ADDED Requirements

### Requirement: Manifest-bound OFF release admission
The OFF deployment tool SHALL admit only the qualified immutable candidate image and its exact source manifest/content digest without assigning the uncommitted source to an inherited owning commit. Before production replacement it SHALL verify current PostgreSQL-copy compatibility and the exact operation implementation's successful and failure-boundary qualification. It SHALL preserve Stable, Companion, shared PostgreSQL identity and schema, durable control/receipt/rotation state and the absence of enabled intent and canary plan.

#### Scenario: Candidate identity is different from historical gate pins
- **WHEN** the qualified image has manifest-owned source rather than the historical gate's owning revision/tree
- **THEN** admission verifies the exact image configuration and full manifest digests, rejects any mismatch, and does not fabricate or truncate a Git identity.

### Requirement: OFF replacement and retained predecessor recovery
The operation SHALL use a private one-attempt journal and a unique gate namespace, prevent application listening before publication, and prove release in the same PID1 epoch/network namespace. A successful cutover SHALL retain the immediate predecessor stopped with restart disabled and its networks disconnected. Rollback SHALL prove the candidate stopped before revoking its gate or restoring the predecessor's exact network/configuration ownership. Unproven recovery SHALL retain a needs-review lock and journal rather than starting a second lane.

#### Scenario: Failure after gate publication
- **WHEN** a candidate fails verification after publication
- **THEN** the transaction disables restart, proves stop, revokes only its own gate, and restores the reviewed immediate predecessor without restoring or migrating production PostgreSQL.

#### Scenario: Successful OFF deployment
- **WHEN** the new Beta is ready and all protected-state checks pass
- **THEN** the canonical Beta lane uses the exact candidate and configured restart policy, the predecessor is retained fenced, and rotation remains OFF without reset, remove, invite or canary execution.
