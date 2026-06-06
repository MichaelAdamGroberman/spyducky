"""OAuth2 scope definitions and validation for spyducky.

Scopes follow the pattern: `service:resource:action`
Example: `conauth:session:create` = continuous-auth service, session resource, create action.

Scope hierarchy:
- `superadmin:*` grants all permissions (spyducky ops only)
- `conauth:tenant:admin` grants all tenant-scoped permissions
- Individual scopes grant specific actions
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from conauth.auth.context import AuthContext


# OAuth2 scope definitions
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

# Scope groups for convenience
SCOPE_GROUPS = {
    "basic_human": {
        "conauth:session:create",
        "conauth:session:read:self",
        "conauth:command:receive",
        "conauth:command:ack",
    },
    "basic_camera": {
        "conauth:stream:write",
    },
    "admin": {
        "conauth:session:read:tenant",
        "conauth:camera:provision",
        "conauth:apikey:issue",
        "conauth:apikey:revoke",
        "conauth:apikey:rotate",
        "conauth:audit:read",
        "conauth:risk:configure",
        "conauth:tenant:admin",
    },
}


class ScopeError(ValueError):
    """Raised when scope validation fails."""

    pass


def validate_scopes(scopes: set[str] | list[str] | frozenset[str]) -> frozenset[str]:
    """Validate and normalize a set of scopes.

    Args:
        scopes: A set, list, or frozenset of scope strings.

    Returns:
        A frozenset of validated scopes.

    Raises:
        ScopeError: If any scope is invalid.
    """
    if isinstance(scopes, (set, list)):
        scopes = frozenset(scopes)
    elif not isinstance(scopes, frozenset):
        raise ScopeError(f"scopes must be a set, list, or frozenset, got {type(scopes)}")

    # Validate each scope
    for scope in scopes:
        if not isinstance(scope, str):
            raise ScopeError(f"Scope must be a string, got {type(scope)}")

        # Check if it's a valid scope or a wildcard
        if not (scope in SCOPES or scope == "superadmin:*" or scope.endswith(":*")):
            # Allow custom scopes for extensibility, but log a warning pattern
            if ":" not in scope:
                raise ScopeError(
                    f"Invalid scope format: {scope}. Scopes must follow pattern 'service:resource:action'"
                )

    return scopes


def require_scope(scope: str) -> callable:
    """FastAPI dependency factory for requiring a specific scope.

    Usage:
        @app.get("/api/sessions")
        async def list_sessions(ctx: AuthContext = Depends(current_auth), _=Depends(require_scope("conauth:session:read:self"))):
            ...

    Args:
        scope: The required scope (e.g., "conauth:session:create").

    Returns:
        An async dependency function for FastAPI.
    """

    async def check_scope(ctx: "AuthContext") -> None:
        """Check that the principal has the required scope."""
        if scope not in ctx.scopes:
            raise ScopeError(f"Principal lacks required scope: {scope}")

    return check_scope


def has_admin_scope(ctx: "AuthContext") -> bool:
    """Check if principal has any admin-level scope.

    Args:
        ctx: The auth context to check.

    Returns:
        True if the principal has admin privileges.
    """
    admin_scopes = SCOPE_GROUPS["admin"]
    return bool(ctx.scopes & admin_scopes)


def has_superadmin_scope(ctx: "AuthContext") -> bool:
    """Check if principal has superadmin scope.

    Args:
        ctx: The auth context to check.

    Returns:
        True if the principal is a superadmin (ops only).
    """
    return "superadmin:*" in ctx.scopes
