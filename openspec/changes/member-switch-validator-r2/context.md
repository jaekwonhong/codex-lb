# Context

Scope: deployed pre-canary package 3cd5952cbe1c9c040b229fd4c993b4ec9b0a2adc7b613b01f04d84571f5548bc,
its actual runtime, active operations scripts and the supplied implementation validators.
The public run state machine and persisted JSON schemas remain unchanged.

The independent oracle is the user's explicit manual-only mandate plus the existing
one-time-fallback and no-replay contracts: count fake driver invocations, retain the
pre-cleanup failure snapshot, and compare persisted owner identity after reconstruction.
An invitation remaining pending is not evidence permitting cancellation/reinvitation.

Historical skipped tests and preserved production evidence are not rewritten into
success. Validation limitations, including real upstream behavior and power-loss
durability, must be stated independently of local test results.
