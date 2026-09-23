## ADDED Requirements

### Requirement: Matched OFF deployment retains durable effect state
The operator tooling SHALL admit the exact built backend image and its canonical
source manifest before releasing its candidate-specific first-start gate. An
inherited image tree label SHALL NOT substitute for the uncommitted source
manifest. Gate release SHALL be atomic and prove the same PID1 epoch and network
namespace across application start. Ambiguous release SHALL stop the candidate
before predecessor recovery. Both backend and Companion durable effect records
SHALL be preserved, and no canary plan SHALL be enabled by OFF deployment.

#### Scenario: Candidate provenance differs
- **WHEN** image or canonical source identity differs from the sealed packet
- **THEN** candidate gate release is denied

#### Scenario: OFF deployment completes
- **WHEN** the matched pair starts
- **THEN** the retained stores remain intact and no automatic effect is authorized

### Requirement: Host signer keeps the private key outside backend mounts
The host signer SHALL retain its Ed25519 private key in a private host directory.
The backend SHALL receive only a read-only observation directory with the public
key and current signed host observations. Signing SHALL bind the exact deployed
Companion executable and registered source identity. A failed signer or stale
observation SHALL block dispatch without resetting any effect budget.
The background signer SHALL use a dedicated installed runtime outside the
development checkout. Qualification SHALL verify automatic observation renewal
through the actual LaunchAgent over longer than one observation validity period.

#### Scenario: Companion binary changes
- **WHEN** the running mapped executable differs from the qualified artifact
- **THEN** the signer rejects it and no fresh authorization observation is emitted

#### Scenario: Background signer cannot start
- **WHEN** an operating-system access prompt prevents the signer from starting
- **THEN** stale observations block dispatch, and qualification does not pass until
  the installed background service renews independently without that prompt

### Requirement: Current OFF operations preserve the qualified deployment
The current OFF operations entrypoint SHALL pin the qualified PostgreSQL identity,
schema, lane storage, backend image and Companion artifact. Before lane mutation
it SHALL require rotation OFF, no active effects and an unchanged receipt store.
Recreation SHALL use the shared operation lock and a fresh first-start gate
namespace, preserve the predecessor and its sentinel, and verify the stopped
candidate configuration before fencing the predecessor. Failed or interrupted
recreation SHALL prove the candidate stopped with restart disabled before
recovering the predecessor. Unproven recovery SHALL retain a needs-review lock.
The recreation and recovery transaction SHALL be qualified in isolation before
its production entrypoint is used.

#### Scenario: Database or OFF state differs
- **WHEN** a pinned database, schema, artifact or OFF-state check fails
- **THEN** lane recreation performs no predecessor mutation

#### Scenario: Candidate start or gate release fails
- **WHEN** recreation cannot prove successful startup
- **THEN** recovery disables candidate restart and proves it stopped before
  restoring the retained predecessor without changing durable effect records
