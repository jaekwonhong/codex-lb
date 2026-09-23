# Optional 5H P2 corrections — 2026-09-19

Normative requirements are in [member-switch commands](spec.md). This correction addresses P2-01 and P2-02 from the independent HOLD review. The original optional-five-hour packet and its sealed independent review remain unchanged historical evidence; the correction does not retrospectively approve their candidate.

## Legacy provenance

Complete legacy pairs with opaque JSON such as `{"source":"live_upstream_fetch","fetch_id":"legacy-fetch"}` remain readable and immutable on retry and new-session recovery. Explicit integer v1, including the full first-party identity fields, remains compatible when it does not carry the newer availability field. v2 retains identity/time/window validation.

Malformed JSON-looking evidence, invalid version types, unsupported versions, duplicate version/availability metadata, v1 with versioned availability, and recognizable missing-version evidence fail closed. A missing-version object remains recognizable when availability metadata or the evaluation/requested-workspace binding signature remains. A single legacy Weekly row never proves normal absence. This structural dispatch is not authentication against arbitrary privileged database rewriting; the existing caller-selected evaluation/epoch boundary is unchanged.

## Operator history

The full `fiveHourState` is passed to the history component. A numeric unknown row displays `5H 미확인` and labels its retained number `보존된 원본 Usage (미검증)`. Valid observed evidence keeps the ordinary final-usage display; not_provided remains `미제공` without a percentage. Original/effective reset separation and invalidation notices are preserved. Weekly presentation and current/replacement member selection are unchanged.

## Qualification and authority

Regression and independent executions use disposable source copies, synthetic SQLite and mocked external effects. The new evidence packet at `/Users/nowtech/Documents/codex-lb-server/artifacts/rotation-optional-five-hour-p2-fix-20260919T132704Z` binds the final source, actual test results, resulting image and bounded OFF decision. It separately records source qualification, image qualification and any failures or limitations.

No source commit/merge, production deployment/restart/database change, activation, live canary, actual reset, member removal or invitation is authorized by this document. Source archive completion and isolated OFF approval are not production or effect authorization.
