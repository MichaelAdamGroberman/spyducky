"""Spyducky authentication & authorization (IAM) module.

Supports three deployment models:
- Multi-tenant SaaS (OIDC via firm IdP)
- On-prem single-tenant (firm OIDC)
- IP cameras (API keys with tiered fallback)

All auth sources resolve to a unified AuthContext.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class AuthContext(BaseModel):
    """Unified authentication context across all auth sources."""

    tenant_id: UUID
    principal_id: UUID
    principal_type: Literal["human", "device"]
    device_class: Literal["browser", "mobile", "ip_camera", "desktop"]
    scopes: frozenset[str]
    auth_session_id: UUID | None = None  # null for API-key auth
    issued_at: datetime
    expires_at: datetime
    source: Literal["oidc_jwt", "refresh_exchange", "api_key", "snapshot_fallback"]
    token_id: str  # jti for JWT, key_id for API key — for audit


# Standard OAuth2/OIDC scopes for continuous auth
SCOPES = {
    # Session management
    "conauth:session:create": "Create a continuous-auth session",
    "conauth:session:read:self": "View own sessions",
    "conauth:session:read:tenant": "View all tenant sessions (admin)",
    # Camera/device streaming
    "conauth:stream:write": "Push H.264 frames to a session (IP cameras)",
    "conauth:stream:read": "Receive stream events",
    # Commands
    "conauth:command:receive": "Receive LOCK/BLACKOUT/ALERT commands",
    "conauth:command:ack": "Acknowledge commands",
    # Camera provisioning
    "conauth:camera:provision": "Bind camera device to session (admin)",
    # API key management
    "conauth:apikey:issue": "Mint an API key (admin)",
    "conauth:apikey:revoke": "Revoke an API key (admin)",
    "conauth:apikey:rotate": "Rotate an API key (admin)",
    # Audit & compliance
    "conauth:audit:read": "Read audit log (admin)",
    "conauth:audit:read:cross_tenant": "Read cross-tenant audit (ops only)",
    # Risk & policy
    "conauth:risk:configure": "Adjust risk policy (admin)",
    "conauth:risk:read": "View risk scores (self)",
    # Tenant management
    "conauth:tenant:admin": "Manage tenant config & OIDC (admin)",
    # Superadmin (spyducky ops only)
    "superadmin:*": "Cross-tenant operations (logged & alerted)",
}

__all__ = ["AuthContext", "SCOPES"]
