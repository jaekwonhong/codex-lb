## ADDED Requirements

### Requirement: Subscription Responses egress omits non-portable reasoning replay items

Before forwarding a Responses request to the subscription upstream, the service MUST remove any input item whose `type` is `reasoning` when that item carries a present non-empty `content` value, or carries a present non-empty `id` that is not a string beginning with `rs_`. The service MUST preserve reasoning items whose content is absent, null, or empty and whose ID is absent/empty or begins with `rs_`. It MUST preserve all non-reasoning input items and their relative order.

This normalization MUST apply only to final subscription egress and MUST NOT alter OpenAI-compatible model-source requests. It MUST NOT mutate the reusable request model used for retry, replay, accounting, or classification.

#### Scenario: Plain model-source reasoning content is omitted before subscription replay

- **GIVEN** a retained thread contains a `reasoning` item with one or more `reasoning_text` content parts from an OpenAI-compatible model source
- **WHEN** the next turn is forwarded to a subscription model
- **THEN** the final subscription payload omits that reasoning item
- **AND** the following assistant message and all other input items remain in their original relative order

#### Scenario: Source-local reasoning ID is omitted before subscription replay

- **GIVEN** a retained thread contains a `reasoning` item whose non-empty ID does not begin with `rs_`
- **WHEN** the next turn is forwarded to a subscription model
- **THEN** the final subscription payload omits that reasoning item instead of forwarding the source-local ID

#### Scenario: Subscription-compatible reasoning item is preserved

- **GIVEN** a retained thread contains a `reasoning` item with absent, null, or empty content and an absent/empty ID or an ID beginning with `rs_`
- **WHEN** the next turn is forwarded to a subscription model
- **THEN** that reasoning item is preserved unchanged

#### Scenario: Model-source forwarding is unchanged

- **WHEN** a Responses request is routed to an OpenAI-compatible model source
- **THEN** this subscription egress normalization does not remove or rewrite its reasoning input items

#### Scenario: Every subscription transport uses the same normalization

- **WHEN** a qualifying request is serialized through subscription HTTP, subscription websocket, direct websocket `response.create`, a size-guarded fresh resend, or the HTTP bridge
- **THEN** each final upstream payload applies the same non-portable reasoning omission rule before byte sizing and transmission
