## MODIFIED Requirements

### Requirement: Workspace Member Controller is the single writer for membership-control state and effects

The Workspace Member Controller SHALL own production workspace membership
switch orchestration, durable effect ownership, unknown-effect state and
no-replay reconciliation. After production ownership transfer, Codex-LB legacy
member-switch creation/command and automatic-rotation writer paths SHALL be
fail-closed, while legacy read/status surfaces MAY remain temporarily available
for inspection and rollback. The qualified Companion SHALL remain an effect
adapter invoked only after the Controller has durably claimed the exact effect;
it SHALL NOT become a second orchestration authority.

#### Scenario: Production WMC accepts a switch command

- **GIVEN** the mutation-enabled WMC is ready with a writable Controller
  persistence principal
- **WHEN** an authenticated caller submits one exact `switch` command
- **THEN** WMC revalidates exact workspace/member identity, durably claims the
  shared no-replay journal, and only then invokes the production Companion
  operation boundary
- **AND** repeating the recorded command identity cannot resend the effect.

#### Scenario: Legacy manual writer is called after cutover

- **GIVEN** Codex-LB is configured with WMC as the workspace membership writer
- **WHEN** a dashboard caller attempts to create or advance a legacy
  member-switch run or change automatic-rotation intent
- **THEN** the write is rejected before any journal/effect change
- **AND** read/status surfaces remain available for rollback inspection.

#### Scenario: Legacy rotation scheduler wakes after cutover

- **GIVEN** WMC owns production workspace membership
- **WHEN** the Codex-LB rotation scheduler ticks
- **THEN** it performs no plan execution or membership-effect work
- **AND** OpenCodex inference routing is unaffected.

### Requirement: Standalone Controller mutation surface is authenticated and explicitly activated

The standalone WMC SHALL default to mutation-disabled mode. Production mutation
routes SHALL exist only when `WMC_MUTATIONS_ENABLED=true`, SHALL remain protected
by the existing Controller bearer admin token, and SHALL require a writable
database principal before readiness. The task-4.4 HTTP surface SHALL expose only
the qualified `switch` action; `add` and `remove` SHALL fail before durable effect
claim until separately qualified.

#### Scenario: Shadow/read-only deployment is started

- **WHEN** `WMC_MUTATIONS_ENABLED` is false
- **THEN** the existing read-only API remains available
- **AND** no production mutation route is exposed or writer privilege required.

#### Scenario: Mutation-enabled deployment uses a read-only database role

- **WHEN** `WMC_MUTATIONS_ENABLED=true` but the database transaction is read-only
- **THEN** startup readiness fails closed
- **AND** no mutation route is promoted ready.
