# Context

The current production member-switch runtime already uses Ego Lite for owner observation/mutations/personal cleanup and for user-facing member OAuth browser work. The remaining managed-flow CDP dependencies are recipient personal/workspace observation and invitation acceptance. `LoginBrowserService` and `UserLoginBrowserService` are separate product surfaces and remain outside this change.
