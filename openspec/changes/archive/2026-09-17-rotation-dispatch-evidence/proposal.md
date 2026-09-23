## Why

The automatic controller evaluates Weekly evidence before asynchronous catalog,
preview, admission, and quota work. That evidence can expire, or its reset
deadline can pass, before the Companion start request. Q3 dispatch must not
remove a member using evidence that became invalid while those calls waited.
The qualified Companion also publishes outgoing identity before DELETE. The
controller currently mistakes this intent for confirmed removal, allowing an
unresolved effect to age out of local quota accounting.

## What Changes

- Reassess the exact decision Weekly receipt at the last local boundary before
  Companion start, after quota accounting has returned.
- Close a rejected pre-effect child through the existing local non-effect path,
  preserving immutable history and releasing only a proven non-effect quota.
- Require exact outgoing identity and the producer's authoritative outgoing
  workspace-absence trace before confirming removal.
- Record the current Q1/Q2 evidence and the separate remaining dispatch gates.

## Impact

The change affects automatic rotation admission only. It adds no scheduler,
runtime activation, schema change, or external membership operation.
