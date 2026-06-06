"""Test that auth module imports and basic structures work."""

import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from conauth.auth import AuthContext, SCOPES


def test_auth_context_creation():
    """AuthContext should be creatable with valid fields."""
    tenant_id = uuid4()
    principal_id = uuid4()
    now = datetime.utcnow()
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
    now = datetime.utcnow()

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
        issued_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(minutes=15),
        source="oidc_jwt",
        token_id="jti-123",
    )

    with pytest.raises(TypeError):
        ctx.scopes.add("conauth:command:receive")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
