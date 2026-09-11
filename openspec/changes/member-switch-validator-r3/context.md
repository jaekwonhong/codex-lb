# Scope and authority

Parent main: fea6a5b4dc39cc45b1ea638148e1c32eea571d71.
Parent manifest: a0009fec505a15e4072a7209a2f60d7787f8b3067da882f9ff3110b42aae8987.

Read-only inspection found 21 current Companion targets and 26 backend legacy
entries, with different fingerprints and only 17 exact identity matches. Because
the existing validator compares the global fingerprints, all create requests are
blocked. Prior integration fixtures made both catalogs identical before requests
and did not exercise this production mismatch.

The existing trusted Companion transport is the managed identity authority, not a
browser-supplied catalog. Snapshot binding is local to the request-scoped auth
service. It does not register new candidates, rewrite the old overlay or authorize
an identity supplied only in a command body. Existing pending/legacy operations are
not adopted. Actual membership/OAuth and whole-OS failure recovery remain outside
the permitted validation; do not retry the invalid R2 checkpoint probe.
