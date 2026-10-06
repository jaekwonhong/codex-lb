"""Standalone workspace-member control-plane domain boundary.

This package must remain independent from Codex-LB request routing, account
repositories, dashboard schemas, and proxy caches.  Runtime adapters may depend
on the package; the domain package must not depend back on those adapters.
"""

