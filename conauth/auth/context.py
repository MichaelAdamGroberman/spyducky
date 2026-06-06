"""AuthContext model and validation for unified authentication.

AuthContext is the single representation of authentication state across all sources:
- OIDC JWT tokens (humans)
- Refresh tokens (humans)
- API keys (IP cameras)
- Fallback snapshot tokens (degraded mode)
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, field_validator, ConfigDict, ValidationError


# Type aliases for validation
PRINCIPAL_TYPES = Literal["human", "device"]
DEVICE_CLASSES = Literal["browser", "mobile", "ip_camera", "desktop"]
AUTH_SOURCES = Literal["oidc_jwt", "refresh_exchange", "api_key", "snapshot_fallback"]

# Type constraints
VALID_PRINCIPAL_TYPES = {"human", "device"}
VALID_DEVICE_CLASSES = {"browser", "mobile", "ip_camera", "desktop"}
VALID_AUTH_SOURCES = {"oidc_jwt", "refresh_exchange", "api_key", "snapshot_fallback"}


class AuthContextError(ValueError):
    """Raised when AuthContext validation fails."""

    pass


class AuthContext(BaseModel):
    """Unified authentication context across all auth sources.

    Represents an authenticated principal (human or device) with their scopes,
    session binding, and metadata about how they authenticated.

    Attributes:
        tenant_id: The UUID of the tenant this principal belongs to.
        principal_id: The UUID of the principal (human or device).
        principal_type: Either "human" or "device".
        device_class: Type of device (browser, mobile, ip_camera, desktop).
        scopes: Immutable set of OAuth2 scopes granted to this principal.
        auth_session_id: UUID of the auth session (null for API-key auth from cameras).
        issued_at: When this token was issued (UTC).
        expires_at: When this token expires (UTC).
        source: How the principal authenticated (OIDC JWT, refresh exchange, API key, or snapshot).
        token_id: Unique token identifier for audit (jti for JWT, key_id for API key).
    """

    tenant_id: UUID
    principal_id: UUID
    principal_type: PRINCIPAL_TYPES
    device_class: DEVICE_CLASSES
    scopes: frozenset[str]
    issued_at: datetime
    expires_at: datetime
    source: AUTH_SOURCES
    token_id: str
    auth_session_id: UUID | None = None  # null for API-key auth

    model_config = ConfigDict(frozen=True)

    @field_validator("principal_type")
    @classmethod
    def validate_principal_type(cls, v: str) -> str:
        """Validate principal_type is one of the allowed values."""
        if v not in VALID_PRINCIPAL_TYPES:
            raise AuthContextError(
                f"Invalid principal_type: {v}. Must be one of {VALID_PRINCIPAL_TYPES}"
            )
        return v

    @field_validator("device_class")
    @classmethod
    def validate_device_class(cls, v: str) -> str:
        """Validate device_class is one of the allowed values."""
        if v not in VALID_DEVICE_CLASSES:
            raise AuthContextError(
                f"Invalid device_class: {v}. Must be one of {VALID_DEVICE_CLASSES}"
            )
        return v

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        """Validate source is one of the allowed values."""
        if v not in VALID_AUTH_SOURCES:
            raise AuthContextError(f"Invalid source: {v}. Must be one of {VALID_AUTH_SOURCES}")
        return v

    @field_validator("scopes")
    @classmethod
    def validate_scopes_format(cls, v: frozenset[str]) -> frozenset[str]:
        """Validate scope format (basic check, not completeness)."""
        for scope in v:
            if not isinstance(scope, str) or not scope:
                raise AuthContextError(f"Invalid scope: {scope}. Scopes must be non-empty strings.")
            if len(scope) > 256:
                raise AuthContextError(f"Scope too long: {scope}. Max 256 characters.")
        return v

    @field_validator("auth_session_id")
    @classmethod
    def validate_auth_session_id(cls, v: UUID | None, info) -> UUID | None:
        """Validate auth_session_id constraint: must be null for device principals."""
        if info.data.get("principal_type") == "device" and v is not None:
            raise AuthContextError(
                "Device principals (ip_camera) must not have auth_session_id. "
                "Only human principals have auth sessions."
            )
        return v

    @field_validator("token_id")
    @classmethod
    def validate_token_id(cls, v: str) -> str:
        """Validate token_id is non-empty and reasonably sized."""
        if not v or len(v) == 0:
            raise AuthContextError("token_id must be non-empty")
        if len(v) > 512:
            raise AuthContextError("token_id too long (max 512 characters)")
        return v

    def has_scope(self, scope: str) -> bool:
        """Check if principal has a specific scope.

        Args:
            scope: The scope to check (e.g., "conauth:session:create").

        Returns:
            True if the principal has the scope, False otherwise.
        """
        return scope in self.scopes

    def has_any_scope(self, scopes: set[str] | list[str]) -> bool:
        """Check if principal has any of the specified scopes.

        Args:
            scopes: A set or list of scopes to check.

        Returns:
            True if the principal has at least one of the scopes.
        """
        return bool(self.scopes & set(scopes))

    def has_all_scopes(self, scopes: set[str] | list[str]) -> bool:
        """Check if principal has all of the specified scopes.

        Args:
            scopes: A set or list of scopes to check.

        Returns:
            True if the principal has all of the scopes.
        """
        return set(scopes).issubset(self.scopes)

    def is_expired(self) -> bool:
        """Check if this auth token is expired.

        Returns:
            True if the token's expiry time is in the past.
        """
        return datetime.now(self.expires_at.tzinfo) >= self.expires_at

    def __repr__(self) -> str:
        """String representation for logging."""
        return (
            f"AuthContext(tenant={self.tenant_id}, principal={self.principal_id}, "
            f"type={self.principal_type}, device={self.device_class}, "
            f"scopes={len(self.scopes)}, source={self.source})"
        )
