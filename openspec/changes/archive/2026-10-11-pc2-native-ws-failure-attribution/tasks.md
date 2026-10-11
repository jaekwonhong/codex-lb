## Implementation

- [x] Add allowlisted native WebSocket receive failure phase propagation through relay message metadata.
- [x] Include the safe phase in HTTP bridge reader-failure diagnostic logs.
- [x] Regression tests for native phases, hostile/missing phase values, and non-native close/reader behavior.

## Validation

- [x] OpenSpec validation.
- [x] Focused adapter/bridge-reader tests.
- [x] Confirm source and Beta runtime remain unaffected.
- [x] Document outcome and rollback (no runtime deployment in this packet).
