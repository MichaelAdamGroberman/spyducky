"""API key management for IP camera authentication.

Issues, verifies, rotates, and revokes API keys. Implements tiered lookup:
  1. Redis cache (5 min TTL) — fast
  2. Postgres query — slower
  3. Signed snapshot file (60s) — degraded (survives IdP+Redis+Postgres outage)
"""

# TODO: Implement API key issue/verify/rotate/revoke
pass
