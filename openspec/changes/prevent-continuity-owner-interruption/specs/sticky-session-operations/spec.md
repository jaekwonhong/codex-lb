## ADDED Requirements

### Requirement: Continuation recovery has a short independent control budget

For an unaccepted foreground response, owner recovery MUST use a cumulative
same-owner wait of at most two seconds and at most five seconds of recovery
control time per logical turn. Nested retries and rebuilt request states MUST NOT
renew these budgets. Normal model generation MUST retain its existing deadline.
The proxy MUST NOT submit to an account before its applicable Retry-After/reset.

#### Scenario: Long owner hold cannot stall the foreground request
- **GIVEN** a continuation owner has a 31-second applicable admission hold
- **WHEN** a new unaccepted turn is processed
- **THEN** the proxy does not wait 31 seconds or retry that owner early
- **AND** it either uses proven safe transfer or returns a classified failure

#### Scenario: Nested recovery does not reset the UX timer
- **GIVEN** one recovery pass has consumed part of a logical turn's control budget
- **WHEN** a nested pass rebuilds its request state
- **THEN** only the original remaining budget is available

### Requirement: Pre-dispatch owner transfer requires complete-context proof

The proxy MAY move an unaccepted turn away from a quota/headroom-pressured owner
before its next upstream send only when existing full-resend verification proves
all required context is present and an authorized healthy alternate is available.
It MUST preserve model, effort, visible history, complete tool call/result pairs,
API-key scope and policy. Client-provided previous-response anchors, file-bound
or account-scoped context and uncertain/accepted operations MUST NOT be moved by
this optimization. Shared owner state MUST NOT be deleted solely on pressure.

#### Scenario: Verified next turn avoids a nearly exhausted owner
- **GIVEN** the previous turn completed and a verified portable full resend exists
- **AND** the owner is pressured and a healthy authorized alternate is available
- **WHEN** the next turn is admitted
- **THEN** no new response is sent to the pressured owner
- **AND** the existing fenced fresh-replay path serves the same conversation

#### Scenario: Unsafe continuation preserves its owner
- **GIVEN** the turn lacks full-context proof or has a file/client-owned anchor
- **WHEN** its owner is pressured
- **THEN** the proxy does not delete the anchor or silently change accounts

### Requirement: Owner failures retain their recovery evidence

Owner error translation MUST retain a structured availability reason and an
available reset/retry hint. A synthetic local cooldown MUST NOT be described as
the time quota is guaranteed to recover. Policy/authentication/ambiguous dispatch
failures MUST NOT become generic transient-owner retries.

#### Scenario: Selection horizon survives error conversion
- **GIVEN** selection reports a required owner's concrete reset horizon
- **WHEN** the bridge emits an owner-unavailable error
- **THEN** callers retain that retry evidence instead of only generic HTTP 502
