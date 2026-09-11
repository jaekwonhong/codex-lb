# Proposal: show and refresh actual workspace membership

The manual member-switch catalog currently shows workspace owners and switch candidates, but it does not show the membership actually observed in each workspace. Add an explicit membership refresh that reads the owner workspace, displays the observed non-owner member(s), and reconciles a known managed account's stored user id when the observed email matches that exact account.

The existing read-only catalog remains side-effect free. Live membership inspection is performed only by the explicit refresh endpoint while no managed switch is active, and once after a successfully finalized manual switch.
