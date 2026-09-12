## ADDED Requirements

### Requirement: Post-registration Force Probe is server-owned
After a current-member OAuth enrollment reaches successful terminal completion with an exact auth account ID, the server SHALL execute the existing Force Probe semantics before returning the successful automatic enrollment response. Browser lifecycle, dashboard request ownership, tab reload state, or component mounting SHALL NOT determine whether the probe runs.

#### Scenario: Quota-exhausted account completes OAuth
- **WHEN** OAuth registration completes for an account whose upstream primary quota is exhausted
- **THEN** the server runs Force Probe for the exact auth account, performs the existing forced usage refresh, persists the resulting diagnostic, and the returned enrollment exposes the refreshed 100% usage result without requiring an operator probe

#### Scenario: Parent account-list refresh occurs while one-click OAuth is running
- **WHEN** the dashboard parent rerenders or replaces its terminal callback while the owning automatic enrollment POST is in flight
- **THEN** the enrollment request remains owned by the same lifecycle, is not aborted by callback identity churn, and normal completion requires no `인증 확인·반영` operator action

### Requirement: Manual and post-registration probes share one orchestration
The OAuth post-registration probe SHALL reuse the same credential refresh, minimal pinned upstream request, forced usage refresh, proxy-health settlement, and audit behavior as the manual account Force Probe route.

The default internal Probe model SHALL be selected from the current host-model registry, preferring `gpt-5.6-luna` and falling back to `gpt-5.5` when Luna is unavailable or suppressed. An explicitly requested Probe model SHALL remain authoritative.

#### Scenario: Probe receives a non-2xx upstream result
- **WHEN** the post-registration probe receives a non-2xx result
- **THEN** the same proxy-health settlement rules used by manual Force Probe are applied and the diagnostic is returned separately from OAuth success

#### Scenario: Probe request is rejected but Usage refresh succeeds
- **WHEN** the minimal Probe request returns a non-2xx HTTP status but credential refresh and the forced Usage fetch succeed for the exact account
- **THEN** the durable diagnostic records both facts and the dashboard reports that OAuth token/Usage retrieval succeeded rather than describing the account as a connection failure

### Requirement: Probe diagnostics are durable and OAuth success remains authoritative
A terminal auth enrollment SHALL persist an optional post-probe diagnostic. Before executing Force Probe, the server SHALL durably claim a single post-probe attempt. Once an attempt has been claimed, concurrent callers and later recovery SHALL NOT automatically execute a second Force Probe. A persisted terminal diagnostic SHALL suppress ordinary repeat probing on retry. If a claimed attempt becomes stale without a durable result, the server SHALL persist an `oauth_probe_outcome_unknown` diagnostic instead of replaying Probe. Probe inability, refresh failure, network failure, unresolved exact account identity, or uncertain post-probe outcome SHALL NOT reverse or retain a successfully completed OAuth enrollment.

#### Scenario: Auto response is retried after completed probe
- **WHEN** a completed automatic enrollment request is retried after its post-probe diagnostic was persisted
- **THEN** the server returns the stored terminal enrollment and does not issue another Force Probe

#### Scenario: Probe fails after OAuth completion
- **WHEN** OAuth is completed but Force Probe fails while refreshing credentials or usage
- **THEN** the enrollment remains completed and the returned durable diagnostic reports the probe failure separately

#### Scenario: Concurrent terminal callers share one probe attempt
- **WHEN** two requests observe the same successful terminal enrollment before a post-probe diagnostic exists
- **THEN** only the durable claim owner executes Force Probe and the other request reads or waits for that attempt's stored result

#### Scenario: Claimed probe outcome becomes unknown
- **WHEN** a post-probe attempt was durably claimed but no diagnostic is persisted before the attempt becomes stale
- **THEN** recovery persists `oauth_probe_outcome_unknown` and does not issue another Force Probe

### Requirement: Dashboard consumes server probe results without owning probe effects
The dashboard SHALL NOT issue the account Probe POST as a follow-up to OAuth completion. It SHALL display the terminal enrollment's server probe diagnostic and refresh account/dashboard read caches so newly persisted quota state is visible promptly.

#### Scenario: Registration returns refreshed quota
- **WHEN** a terminal enrollment response contains a successful server probe diagnostic
- **THEN** the dashboard shows the probe result and refreshes the account views without sending a second probe request
