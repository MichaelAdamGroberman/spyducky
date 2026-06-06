"""Test that auth module imports, validation, and basic structures work."""

import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from pydantic import ValidationError

from conauth.auth import AuthContext, SCOPES, validate_scopes, require_scope, AuthContextError
from conauth.auth.context import VALID_PRINCIPAL_TYPES, VALID_DEVICE_CLASSES
from conauth.auth.scopes import ScopeError, has_admin_scope, has_superadmin_scope


def test_auth_context_creation():
    """AuthContext should be creatable with valid fields."""
    tenant_id = uuid4()
    principal_id = uuid4()
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=15)

    ctx = AuthContext(
        tenant_id=tenant_id,
        principal_id=principal_id,
        principal_type="human",
        device_class="browser",
        scopes=frozenset(["conauth:session:create"]),
        issued_at=now,
        expires_at=exp,
        source="oidc_jwt",
        token_id="jti-123",
    )

    assert ctx.tenant_id == tenant_id
    assert ctx.principal_id == principal_id
    assert ctx.principal_type == "human"
    assert "conauth:session:create" in ctx.scopes


def test_auth_context_device():
    """AuthContext should support device principals (no auth_session_id)."""
    tenant_id = uuid4()
    principal_id = uuid4()
    now = datetime.now(timezone.utc)

    ctx = AuthContext(
        tenant_id=tenant_id,
        principal_id=principal_id,
        principal_type="device",
        device_class="ip_camera",
        scopes=frozenset(["conauth:stream:write"]),
        issued_at=now,
        expires_at=now + timedelta(days=365),
        source="api_key",
        token_id="key_id_abc",
        auth_session_id=None,
    )

    assert ctx.principal_type == "device"
    assert ctx.auth_session_id is None


def test_scopes_defined():
    """All expected scopes should be defined."""
    assert "conauth:session:create" in SCOPES
    assert "conauth:stream:write" in SCOPES
    assert "conauth:apikey:issue" in SCOPES
    assert "superadmin:*" in SCOPES


def test_auth_context_scopes_frozen():
    """AuthContext scopes should be immutable (frozenset)."""
    ctx = AuthContext(
        tenant_id=uuid4(),
        principal_id=uuid4(),
        principal_type="human",
        device_class="browser",
        scopes=frozenset(["conauth:session:create"]),
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        source="oidc_jwt",
        token_id="jti-123",
    )

    # frozenset has no add method
    with pytest.raises(AttributeError):
        ctx.scopes.add("conauth:command:receive")  # type: ignore


def test_auth_context_validation_invalid_principal_type():
    """AuthContext should reject invalid principal types."""
    with pytest.raises(ValidationError):
        AuthContext(
            tenant_id=uuid4(),
            principal_id=uuid4(),
            principal_type="invalid_type",  # type: ignore
            device_class="browser",
            scopes=frozenset(["conauth:session:create"]),
            issued_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
            source="oidc_jwt",
            token_id="jti-123",
        )


def test_auth_context_validation_invalid_device_class():
    """AuthContext should reject invalid device classes."""
    with pytest.raises(ValidationError):
        AuthContext(
            tenant_id=uuid4(),
            principal_id=uuid4(),
            principal_type="human",
            device_class="invalid_device",  # type: ignore
            scopes=frozenset(["conauth:session:create"]),
            issued_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
            source="oidc_jwt",
            token_id="jti-123",
        )


def test_auth_context_validation_device_no_auth_session():
    """Device principals must not have auth_session_id."""
    with pytest.raises(ValidationError):
        AuthContext(
            tenant_id=uuid4(),
            principal_id=uuid4(),
            principal_type="device",
            device_class="ip_camera",
            scopes=frozenset(["conauth:stream:write"]),
            issued_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=365),
            source="api_key",
            token_id="key_id_abc",
            auth_session_id=uuid4(),  # should not be allowed for devices
        )


def test_auth_context_has_scope():
    """AuthContext.has_scope() should check for a specific scope."""
    ctx = AuthContext(
        tenant_id=uuid4(),
        principal_id=uuid4(),
        principal_type="human",
        device_class="browser",
        scopes=frozenset(["conauth:session:create", "conauth:command:receive"]),
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        source="oidc_jwt",
        token_id="jti-123",
    )

    assert ctx.has_scope("conauth:session:create")
    assert not ctx.has_scope("conauth:apikey:issue")


def test_auth_context_has_any_scope():
    """AuthContext.has_any_scope() should check for any of multiple scopes."""
    ctx = AuthContext(
        tenant_id=uuid4(),
        principal_id=uuid4(),
        principal_type="human",
        device_class="browser",
        scopes=frozenset(["conauth:session:create"]),
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        source="oidc_jwt",
        token_id="jti-123",
    )

    assert ctx.has_any_scope(["conauth:session:create", "conauth:apikey:issue"])
    assert not ctx.has_any_scope(["conauth:apikey:issue", "conauth:apikey:revoke"])


def test_auth_context_has_all_scopes():
    """AuthContext.has_all_scopes() should check for all of multiple scopes."""
    ctx = AuthContext(
        tenant_id=uuid4(),
        principal_id=uuid4(),
        principal_type="human",
        device_class="browser",
        scopes=frozenset(["conauth:session:create", "conauth:command:receive", "conauth:command:ack"]),
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        source="oidc_jwt",
        token_id="jti-123",
    )

    assert ctx.has_all_scopes(["conauth:session:create", "conauth:command:receive"])
    assert not ctx.has_all_scopes(["conauth:session:create", "conauth:apikey:issue"])


def test_auth_context_is_expired():
    """AuthContext.is_expired() should detect expired tokens."""
    now = datetime.now(timezone.utc)
    expired_ctx = AuthContext(
        tenant_id=uuid4(),
        principal_id=uuid4(),
        principal_type="human",
        device_class="browser",
        scopes=frozenset(["conauth:session:create"]),
        issued_at=now - timedelta(hours=1),
        expires_at=now - timedelta(minutes=1),  # expired 1 minute ago
        source="oidc_jwt",
        token_id="jti-123",
    )

    assert expired_ctx.is_expired()

    valid_ctx = AuthContext(
        tenant_id=uuid4(),
        principal_id=uuid4(),
        principal_type="human",
        device_class="browser",
        scopes=frozenset(["conauth:session:create"]),
        issued_at=now,
        expires_at=now + timedelta(minutes=15),  # expires in 15 minutes
        source="oidc_jwt",
        token_id="jti-123",
    )

    assert not valid_ctx.is_expired()


def test_validate_scopes():
    """validate_scopes() should normalize and validate scope sets."""
    scopes_list = ["conauth:session:create", "conauth:command:receive"]
    result = validate_scopes(scopes_list)
    assert isinstance(result, frozenset)
    assert "conauth:session:create" in result

    # Should accept frozensets
    result = validate_scopes(frozenset(scopes_list))
    assert isinstance(result, frozenset)

    # Should reject invalid scope format
    with pytest.raises(ScopeError, match="Invalid scope format"):
        validate_scopes(["invalid_scope_no_colon"])


def test_has_admin_scope():
    """has_admin_scope() should detect admin-level scopes."""
    admin_ctx = AuthContext(
        tenant_id=uuid4(),
        principal_id=uuid4(),
        principal_type="human",
        device_class="browser",
        scopes=frozenset(["conauth:apikey:issue"]),
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        source="oidc_jwt",
        token_id="jti-123",
    )

    assert has_admin_scope(admin_ctx)

    user_ctx = AuthContext(
        tenant_id=uuid4(),
        principal_id=uuid4(),
        principal_type="human",
        device_class="browser",
        scopes=frozenset(["conauth:session:create"]),
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        source="oidc_jwt",
        token_id="jti-123",
    )

    assert not has_admin_scope(user_ctx)


def test_has_superadmin_scope():
    """has_superadmin_scope() should detect superadmin scope."""
    superadmin_ctx = AuthContext(
        tenant_id=uuid4(),
        principal_id=uuid4(),
        principal_type="human",
        device_class="browser",
        scopes=frozenset(["superadmin:*"]),
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        source="oidc_jwt",
        token_id="jti-123",
    )

    assert has_superadmin_scope(superadmin_ctx)

    user_ctx = AuthContext(
        tenant_id=uuid4(),
        principal_id=uuid4(),
        principal_type="human",
        device_class="browser",
        scopes=frozenset(["conauth:session:create"]),
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        source="oidc_jwt",
        token_id="jti-123",
    )

    assert not has_superadmin_scope(user_ctx)


def test_auth_context_immutable():
    """AuthContext should be immutable (frozen)."""
    ctx = AuthContext(
        tenant_id=uuid4(),
        principal_id=uuid4(),
        principal_type="human",
        device_class="browser",
        scopes=frozenset(["conauth:session:create"]),
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        source="oidc_jwt",
        token_id="jti-123",
    )

    with pytest.raises((AttributeError, ValueError)):  # Pydantic frozen raises AttributeError or ValidationError
        ctx.scopes = frozenset(["conauth:apikey:issue"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
