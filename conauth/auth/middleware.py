"""FastAPI middleware and dependency injection for authentication.

Provides:
- current_auth: FastAPI Depends that validates and returns AuthContext
- current_tenant: Injects tenant_id contextvar
- with_tenant: DB connection wrapper that sets SET LOCAL app.tenant_id
- Cross-tenant assertion middleware
"""

# TODO: Implement auth middleware and dependencies
pass
