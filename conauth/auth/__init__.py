"""Spyducky authentication & authorization (IAM) module.

Supports three deployment models:
- Multi-tenant SaaS (OIDC via firm IdP)
- On-prem single-tenant (firm OIDC)
- IP cameras (API keys with tiered fallback)

All auth sources resolve to a unified AuthContext.
"""

from conauth.auth.context import AuthContext, AuthContextError, PRINCIPAL_TYPES, DEVICE_CLASSES, AUTH_SOURCES
from conauth.auth.scopes import SCOPES, validate_scopes, require_scope

__all__ = [
    "AuthContext",
    "AuthContextError",
    "SCOPES",
    "PRINCIPAL_TYPES",
    "DEVICE_CLASSES",
    "AUTH_SOURCES",
    "validate_scopes",
    "require_scope",
]
