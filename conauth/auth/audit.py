"""Audit logging with tamper-evident hash chain.

Emits auth events to Redis Stream audit:auth → drain worker → Postgres.
Hash chain: each row commits to previous row's hash.
Hourly verifier detects tampering.
"""

# TODO: Implement audit emission and hash chain verification
pass
