## 1. Contract

- [x] Add a durable OAuth-enrollment browser-open action and typed result fields.
- [x] Add a trusted Companion Ego Lite endpoint that revalidates exact member/profile identity.

## 2. Host integration

- [x] Resolve deterministic Ego profile ids from stable account-pool account ids.
- [x] Invoke the local Ego runtime without shell interpolation or default-browser fallback.
- [x] Create/reuse only the exact enrollment task space and hand it to the user.
- [x] Preserve explicit failure/unknown outcomes without implicit retry.

## 3. Dashboard

- [x] Replace the raw verification hyperlink with an explicit Ego Lite browser command.
- [x] Surface profile/task-space state and actionable failure codes.

## 4. Qualification and provisioning

- [x] Add positive and negative backend/Companion/UI regressions for profile identity and response loss.
- [x] Validate Ego native API behavior with disposable task spaces only.
- [x] Provide a guarded host provisioning tool for missing deterministic profiles.
- [ ] Keep operational runtime unchanged until the candidate is independently qualified and deployed. Independent worker review is currently unavailable; direct qualification evidence is retained instead.
