# Usage-driven Business member rotation

Add a Beta-only, default-off foundation for usage-driven ChatGPT Business member replacement. A replacement may become eligible only after the current workspace member has a freshly observed, actually weekly usage window that is exhausted, any applicable reset credit has been resolved through the existing serialized redemption path, and the workspace passes conservative rolling replacement limits.

The change reuses the current durable member-switch ownership/no-replay model. It separates Weekly observation, reset-credit resolution, quota/history accounting, and Companion response telemetry so those foundations can be implemented and qualified independently before a controller is connected to membership effects.

The first implementation does not infer OpenAI's undocumented churn limit, does not couple replacement to paid-seat reduction, and does not authorize repeated live experiments. Live member effects remain disabled until the parallel foundations are integrated, independently reviewed, and a legitimate final canary is admitted.
