## ADDED Requirements

### Requirement: Canary artifact qualification identifies the exact uncommitted source

The 2.11.48-canary.1 source candidate SHALL be qualified only by the registered
exact version, published executable SHA-256 and canonical source-file manifest
SHA-256. An uncommitted candidate SHALL carry no owning Git commit. A missing or
altered source digest, binary digest, or invented owning commit SHALL fail closed.
Historical P4 version/hash/owning-commit qualification SHALL remain a separate
tuple and SHALL NOT certify the new candidate. Artifact qualification SHALL NOT
substitute for a current signed host observation, Canary capability, enabled
operator plan, Weekly/reset/quota evidence or the single-use effect budget.

#### Scenario: A source digest is substituted on the new binary
- **GIVEN** the registered Canary executable hash
- **WHEN** the asserted source-manifest hash differs
- **THEN** runtime attestation and automatic dispatch reject the candidate

#### Scenario: A historical owning commit is assigned to the candidate
- **WHEN** the new candidate carries the old P4 owning commit
- **THEN** the provenance assertion is rejected
